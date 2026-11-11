/**
 * 静态站点数据层（只在 GitHub Pages 那份「静态导出站」里加载）。
 *
 * 项目的正常版本是 Flask 后端 + Jinja2 服务端渲染；但要挂到 GitHub Pages 这类
 * 只能放静态文件的平台上，就得把后端的活搬到浏览器里：
 *
 *   1. 导出脚本把数据库导成 data/*.json 数据包（区域数据按“经济体 + 层级”分文件）；
 *   2. 本文件接管 GDP.getJSON()，用同一份数据在浏览器里算出各接口的返回结果，
 *      响应结构与 webapp/app.py 的 JSON 接口逐字段对齐（筛选、排序、口径都不变）；
 *   3. 少数页面（排行榜、数据集）的表格原本由服务端渲染，这里改为前端重画，
 *      这样年份/指标/关键词等控件在静态站上依然可用；
 *   4. 采集相关的入口在导出的 HTML 里就已经关掉了（导出时按“公共演示模式”渲染）。
 *
 * 因此静态站是**只读快照**：浏览、筛选、下钻、导出 CSV 都能用，只有采集不可用。
 * 数据口径与在线版完全一致——口径一旦分叉，两边的结论就会不一样。
 */
(function () {
  "use strict";

  if (!window.GDP) {
    // charts.js 必须先加载：这里的格式化与图表绘制都复用它
    console.warn("static-api.js 需要在 charts.js 之后加载");
    return;
  }

  var DATA_DIR = "data/";
  var METRIC_NAMES = { gdp: "GDP 总量", per_capita: "人均 GDP", growth: "同比增速" };
  var LEVEL_NAMES = {
    province: "省级行政区", city: "地级行政区（城市）", state: "州级行政区",
    county: "县级行政区（县）", prefecture: "都道府县"
  };
  var ECONOMY_NAMES = { CHN: "中国", USA: "美国", JPN: "日本" };
  var REGION_METRICS = { gdp: "gdp_native", increment: "increment_native", growth: "growth_rate" };

  var cache = {};
  function load(name) {
    if (!cache[name]) {
      cache[name] = fetch(DATA_DIR + name).then(function (response) {
        if (!response.ok) { throw new Error("静态数据缺失：" + name); }
        return response.json();
      });
    }
    return cache[name];
  }

  // ==================================================================
  // 数据索引（加载后建一次，之后所有查询都在内存里算）
  // ==================================================================
  var store = { ready: false };
  var readyPromise = null;

  function prepare() {
    if (readyPromise) { return readyPromise; }
    readyPromise = Promise.all([
      load("meta.json"), load("country.json"), load("annual.json"),
      load("quarter.json"), load("rank.json"), load("rankseries.json"),
      load("dataset.json"), load("crawl.json")
    ]).then(function (items) {
      store.meta = items[0];
      store.countries = items[1];
      store.annual = items[2];
      store.quarter = items[3];
      store.rank = items[4];
      store.rankseries = items[5];
      store.dataset = items[6];
      store.crawl = items[7];

      store.countryByCode = {};
      store.countries.forEach(function (item) { store.countryByCode[item.code] = item; });

      // 年度序列：{国家代码: [[年, GDP, 人均], ...]}，年份升序
      store.seriesByCode = {};
      store.annual.forEach(function (row) {
        (store.seriesByCode[row[0]] = store.seriesByCode[row[0]] || []).push([row[1], row[2], row[3]]);
      });
      store.ready = true;
      return store;
    });
    return readyPromise;
  }

  function loadRegion(economy, level) {
    var name = "region-" + economy + "-" + level + ".json";
    return load(name).then(function (pack) {
      if (!pack.decoded) {
        pack.decoded = pack.rows.map(function (values) {
          var item = { economy: pack.economy, level: pack.level };
          pack.cols.forEach(function (col, index) { item[col] = values[index]; });
          if (typeof item.source === "number") { item.source = pack.sources[item.source]; }
          return item;
        });
      }
      return pack.decoded;
    });
  }

  // ==================================================================
  // 与 analysis/indicators.py 对应的纯函数（口径必须一致）
  // ==================================================================
  function yoyGrowth(pairs) {
    var result = [], previous = null;
    pairs.forEach(function (pair) {
      if (previous && previous[1]) {
        result.push([pair[0], (pair[1] - previous[1]) / previous[1] * 100.0]);
      }
      previous = pair;
    });
    return result;
  }

  function gapRatio(seriesA, seriesB) {
    var index = {};
    seriesB.forEach(function (pair) { index[pair[0]] = pair[1]; });
    var result = [];
    seriesA.forEach(function (pair) {
      var other = index[pair[0]];
      if (other) { result.push([pair[0], pair[1] / other]); }
    });
    return result;
  }

  function compareSummary(seriesA, seriesB, nameA, nameB) {
    var ratios = gapRatio(seriesA, seriesB);
    if (!ratios.length) { return {}; }
    var lowest = ratios[0], highest = ratios[0];
    ratios.forEach(function (pair) {
      if (pair[1] < lowest[1]) { lowest = pair; }
      if (pair[1] > highest[1]) { highest = pair; }
    });
    var last = ratios[ratios.length - 1];
    return {
      latest_year: last[0], latest_ratio: last[1],
      first_year: ratios[0][0], first_ratio: ratios[0][1],
      highest_year: highest[0], highest_ratio: highest[1],
      lowest_year: lowest[0], lowest_ratio: lowest[1],
      label_a: nameA, label_b: nameB
    };
  }

  function rankProgress(pairs) {
    if (!pairs.length) { return {}; }
    var best = pairs[0];
    pairs.forEach(function (pair) { if (pair[1] < best[1]) { best = pair; } });
    return {
      first_year: pairs[0][0], first_rank: pairs[0][1],
      latest_year: pairs[pairs.length - 1][0], latest_rank: pairs[pairs.length - 1][1],
      best_year: best[0], best_rank: best[1]
    };
  }

  function singleQuarter(records) {
    var result = [], previous = null;
    records.forEach(function (row) {
      var value = row.gdp_yi;
      if (value === null || value === undefined) { return; }
      var year = parseInt(String(row.period).slice(0, 4), 10);
      var quarter = parseInt(String(row.period).slice(5), 10);
      var single;
      if (quarter === 1) {
        single = value;
      } else if (previous && previous.year === year && previous.quarter === quarter - 1) {
        single = value - previous.value;
      } else {
        previous = { year: year, quarter: quarter, value: value };
        return;
      }
      result.push({ period: row.period, year: year, quarter: quarter, value: Math.round(single * 100) / 100 });
      previous = { year: year, quarter: quarter, value: value };
    });
    return result;
  }

  function industryStructure(records) {
    var result = [];
    records.forEach(function (row) {
      var total = row.gdp_yi;
      if (!total) { return; }
      result.push({
        period: row.period,
        year: parseInt(String(row.period).slice(0, 4), 10),
        quarter: parseInt(String(row.period).slice(5), 10),
        first: (row.first_yi || 0) / total * 100.0,
        second: (row.second_yi || 0) / total * 100.0,
        third: (row.third_yi || 0) / total * 100.0
      });
    });
    return result;
  }

  // ==================================================================
  // 数值工具（与 DAO 的 SQL 语义对齐）
  // ==================================================================
  function round(value, digits) {
    if (value === null || value === undefined) { return value; }
    var factor = Math.pow(10, digits);
    // 大数先乘再除会超出双精度整数范围（2^53），反而引入误差；这种量级本来也无需保留小数
    if (Math.abs(value) * factor >= 9007199254740992) { return value; }
    return Math.round(value * factor) / factor;
  }

  function like(value, keyword) {
    // SQLite 的 LIKE 对 ASCII 不区分大小写，这里同样处理，保证筛选结果一致
    if (value === null || value === undefined) { return false; }
    return String(value).toLowerCase().indexOf(String(keyword).toLowerCase()) >= 0;
  }

  function sortedBy(items, column, tieField) {
    // 对应 SQL：ORDER BY <列> IS NULL, <列> DESC, <tieField>
    // （缺失值排在最后；数值并列时按代码排序，与后端一样保证顺序确定）
    return items.slice().sort(function (a, b) {
      var left = a[column], right = b[column];
      var leftNull = (left === null || left === undefined) ? 1 : 0;
      var rightNull = (right === null || right === undefined) ? 1 : 0;
      if (leftNull !== rightNull) { return leftNull - rightNull; }
      if (right !== left) { return right - left; }
      if (!tieField) { return 0; }
      var leftKey = String(a[tieField]), rightKey = String(b[tieField]);
      return leftKey < rightKey ? -1 : (leftKey > rightKey ? 1 : 0);
    });
  }

  function seriesOf(code, metric, start, end) {
    var rows = store.seriesByCode[code] || [];
    var column = metric === "per_capita" ? 2 : 1;
    var result = [];
    rows.forEach(function (row) {
      if (row[column] === null || row[column] === undefined) { return; }
      if (start && row[0] < start) { return; }
      if (end && row[0] > end) { return; }
      result.push([row[0], row[column]]);
    });
    return result;
  }

  function rankOf(code, year, metric) {
    var byYear = store.rank[String(year)] || {};
    var items = byYear[metric] || [];
    var own = null;
    items.forEach(function (item) { if (item.code === code) { own = item.value; } });
    if (own === null) { return null; }
    var above = 0;
    items.forEach(function (item) { if (item.value > own) { above += 1; } });
    return above + 1;
  }

  function worldTotal(year) {
    var total = 0;
    store.annual.forEach(function (row) {
      if (row[1] !== year || row[2] === null || row[2] === undefined) { return; }
      var country = store.countryByCode[row[0]];
      if (country && country.is_aggregate) { return; }
      total += row[2];
    });
    return total;
  }

  // ==================================================================
  // 接口实现（响应结构与 webapp/app.py 一致）
  // ==================================================================
  var api = {
    "/api/summary": function (params) {
      var meta = store.meta;
      var years = meta.years;
      if (!years.length) { return { empty: true }; }
      var latest = (params.year && years.indexOf(Number(params.year)) >= 0) ? Number(params.year) : years[0];
      var byYear = store.rank[String(latest)] || {};
      var top = (byYear.gdp || [])[0] || null;
      var total = worldTotal(latest);
      var china = seriesOf("CHN", "gdp", latest, latest);
      var chinaPc = seriesOf("CHN", "per_capita", latest, latest);
      var usa = seriesOf("USA", "gdp", latest, latest);
      var chinaValue = china.length ? china[0][1] : 0.0;
      var usaValue = usa.length ? usa[0][1] : 0.0;
      var chinaHistory = seriesOf("CHN", "gdp", null, null);
      var chinaPcHistory = seriesOf("CHN", "per_capita", null, null);
      var rankSeries = (store.rankseries.gdp || {}).CHN || [];
      return {
        empty: false,
        latest_year: latest,
        year_range: meta.year_range,
        country_count: meta.counts.country,
        record_count: meta.counts.annual,
        world_total: total,
        top_country: top,
        china_value: chinaValue,
        china_share: total ? (chinaValue / total * 100.0) : 0.0,
        china_rank: rankOf("CHN", latest, "gdp"),
        china_rank_start: rankSeries.length ? rankSeries[0] : [null, null],
        china_per_capita: chinaPc.length ? chinaPc[0][1] : null,
        china_per_capita_rank: rankOf("CHN", latest, "per_capita"),
        china_first_year: chinaHistory.length ? chinaHistory[0][0] : null,
        china_first_value: chinaHistory.length ? chinaHistory[0][1] : null,
        china_multiple: (chinaHistory.length && chinaHistory[0][1]) ? (chinaValue / chinaHistory[0][1]) : null,
        china_per_capita_first: chinaPcHistory.length ? chinaPcHistory[0][1] : null,
        china_per_capita_multiple: (chinaPc.length && chinaPcHistory.length && chinaPcHistory[0][1])
          ? (chinaPc[0][1] / chinaPcHistory[0][1]) : null,
        usa_value: usaValue,
        china_vs_usa: usaValue ? (chinaValue / usaValue * 100.0) : 0.0,
        crawl_total: meta.counts.quarter,
        last_update: meta.snapshot_time
      };
    },

    "/api/countries": function (params) {
      var keyword = params.keyword;
      var items = store.countries.filter(function (item) { return !item.is_aggregate; });
      if (keyword) {
        items = items.filter(function (item) {
          return like(item.name_cn, keyword) || like(item.name_en, keyword) || like(item.code, keyword);
        });
      }
      items = items.slice().sort(function (a, b) {
        // SQLite 的 ORDER BY name_cn 是二进制序（按码点），不是拼音序
        var left = String(a.name_cn), right = String(b.name_cn);
        return left < right ? -1 : (left > right ? 1 : 0);
      });
      if (params.limit) { items = items.slice(0, Number(params.limit)); }
      return { items: items };
    },

    "/api/rank": function (params) {
      var years = store.meta.years;
      var year = (params.year && years.indexOf(Number(params.year)) >= 0) ? Number(params.year) : years[0];
      var metric = params.metric === "per_capita" ? "per_capita" : "gdp";
      var limit = clamp(params.limit, 15, 5, 50);
      var byYear = store.rank[String(year)] || {};
      var items = (byYear[metric] || []).slice(0, limit);
      return { year: year, metric: metric, metric_name: METRIC_NAMES[metric], items: items };
    },

    "/api/trend": function (params) {
      var metric = (params.metric === "per_capita" || params.metric === "growth") ? params.metric : "gdp";
      var codes = codesOf(params, store.meta.focus_countries);
      var base = metric === "growth" ? "gdp" : metric;
      var start = params.start ? Number(params.start) : null;
      var end = params.end ? Number(params.end) : null;
      var items = [];
      codes.forEach(function (code) {
        var pairs = seriesOf(code, base, start, end);
        if (!pairs.length) { return; }
        var country = store.countryByCode[code] || {};
        var name = country.name_cn || code;
        var values = metric === "growth" ? yoyGrowth(pairs) : pairs;
        items.push({
          code: code, name: name,
          label: metric === "growth" ? (name + " 同比增速") : name,
          data: values.map(function (pair) { return [pair[0], round(pair[1], 4)]; })
        });
      });
      return { metric: metric, metric_name: METRIC_NAMES[metric], items: items };
    },

    "/api/compare": function (params) {
      var metric = params.metric === "per_capita" ? "per_capita" : "gdp";
      var codes = codesOf(params, ["CHN", "USA"], 4);
      var items = [], series = {};
      codes.forEach(function (code) {
        var pairs = seriesOf(code, metric, null, null);
        series[code] = pairs;
        var country = store.countryByCode[code] || {};
        items.push({
          code: code, name: country.name_cn || code,
          data: pairs.map(function (pair) { return [pair[0], round(pair[1], 2)]; })
        });
      });
      var summary = {};
      if (codes.length >= 2 && series[codes[0]].length && series[codes[1]].length) {
        var nameA = (store.countryByCode[codes[0]] || {}).name_cn || codes[0];
        var nameB = (store.countryByCode[codes[1]] || {}).name_cn || codes[1];
        summary = compareSummary(series[codes[0]], series[codes[1]], nameA, nameB);
        summary.ratio_data = gapRatio(series[codes[0]], series[codes[1]]).map(function (pair) {
          return [pair[0], round(pair[1], 4)];
        });
      }
      return { metric: metric, metric_name: METRIC_NAMES[metric], items: items, summary: summary };
    },

    "/api/share": function (params) {
      var years = store.meta.years;
      var year = (params.year && years.indexOf(Number(params.year)) >= 0) ? Number(params.year) : years[0];
      var topN = clamp(params.top, 10, 5, 20);
      var total = worldTotal(year);
      var byYear = store.rank[String(year)] || {};
      var top = (byYear.gdp || []).slice(0, topN);
      var items = [];
      var topSum = 0;
      if (total) {
        top.forEach(function (item) {
          topSum += item.value;
          items.push({ name: item.name_cn, code: item.code, value: item.value,
                       ratio: item.value / total * 100.0 });
        });
        var rest = total - topSum;
        if (rest > 0) {
          items.push({ name: "其他国家", code: "REST", value: rest, ratio: rest / total * 100.0 });
        }
      }
      return { year: year, total: total, items: items };
    },

    "/api/china/quarter": function () {
      var records = store.quarter;
      var singles = singleQuarter(records);
      var structure = industryStructure(records);
      return {
        periods: records.map(function (row) { return row.period; }),
        labels: records.map(function (row) { return row.period_label; }),
        cumulative: records.map(function (row) { return [row.period, row.gdp_yi]; }),
        single: singles.map(function (item) { return [item.period, item.value]; }),
        yoy: records.map(function (row) { return [row.period, row.gdp_yoy]; }),
        structure: structure.map(function (item) {
          return [item.period, round(item.first, 2), round(item.second, 2), round(item.third, 2)];
        }),
        records: records.map(function (row) {
          return { period: row.period, label: row.period_label, gdp: row.gdp_yi,
                   first: row.first_yi, second: row.second_yi, third: row.third_yi,
                   yoy: row.gdp_yoy, first_yoy: row.first_yoy,
                   second_yoy: row.second_yoy, third_yoy: row.third_yoy };
        }),
        latest: records.length ? records[records.length - 1] : null,
        count: records.length
      };
    },

    "/api/china/rank": function (params) {
      var code = (params.code || "CHN").toUpperCase();
      var metric = params.metric === "per_capita" ? "per_capita" : "gdp";
      var byMetric = store.rankseries[metric] || {};
      var pairs = (byMetric[code] || []).map(function (pair) { return [pair[0], pair[1]]; });
      var country = store.countryByCode[code] || {};
      return { code: code, name: country.name_cn || code, metric: metric,
               items: pairs, summary: rankProgress(pairs) };
    },

    "/api/dataset": function (params) {
      var metric = params.metric === "per_capita" ? "per_capita" : "gdp";
      var year = params.year ? Number(params.year) : null;
      var country = params.country || null;
      var size = clamp(params.size, 20, 5, 200);
      var page = Math.max(1, Number(params.page) || 1);
      var column = metric === "per_capita" ? 3 : 2;
      var rows = store.dataset.rows.filter(function (row) {
        if (row[column] === null || row[column] === undefined) { return false; }
        if (year && row[1] !== year) { return false; }
        if (country) {
          var info = store.countryByCode[row[0]] || {};
          if (!like(row[0], country) && !like(info.name_cn, country)) { return false; }
        }
        return true;
      });
      rows = rows.slice().sort(function (a, b) {
        if (a[1] !== b[1]) { return b[1] - a[1]; }
        if (b[column] !== a[column]) { return b[column] - a[column]; }
        return a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0);      // 并列时按国家代码
      });
      var items = rows.slice((page - 1) * size, page * size).map(function (row) {
        var info = store.countryByCode[row[0]] || {};
        return { code: row[0], name_cn: info.name_cn, name_en: info.name_en,
                 region: info.region, income_level: info.income_level, year: row[1],
                 gdp_usd: row[2], gdp_per_capita_usd: row[3] };
      });
      return { total: rows.length, items: items };
    },

    "/api/region/levels": function (params) {
      var economy = economyOf(params);
      return regionLevelsPayload(economy);
    },

    "/api/region/rank": function (params) {
      var economy = economyOf(params);
      var meta = store.meta;
      var levels = (meta.levels[economy] || []);
      if (!levels.length) {
        return { economy: economy, level: "", year: null, mode: "year", metric: "gdp",
                 level_name: "", currency: "CNY", total: 0, areas: 0, items: [], year_distribution: [] };
      }
      var level = params.level || levels[0].level;
      if (!levels.some(function (item) { return item.level === level; })) { level = levels[0].level; }
      var years = regionYears(economy, level);
      var year = params.year ? Number(params.year) : (years.length ? years[0] : null);
      if (years.length && years.indexOf(year) < 0) { year = years[0]; }
      var mode = params.mode === "latest" ? "latest" : "year";
      var metric = (params.metric === "growth" || params.metric === "increment") ? params.metric : "gdp";
      var limit = clamp(params.limit, 20, 5, 400);
      var keyword = params.keyword || null;

      return loadRegion(economy, level).then(function (rows) {
        var column = REGION_METRICS[metric] || "gdp_native";
        var pool, total, areas;
        if (mode === "latest") {
          var latestByCode = {};
          rows.forEach(function (row) {
            var key = row.region_code;
            if (!latestByCode[key] || row.year > latestByCode[key].year) { latestByCode[key] = row; }
          });
          pool = [];
          Object.keys(latestByCode).forEach(function (key) {
            if (latestByCode[key][column] !== null && latestByCode[key][column] !== undefined) {
              pool.push(latestByCode[key]);
            }
          });
          if (keyword) { pool = pool.filter(function (row) { return matchesKeyword(row, keyword); }); }
          total = 0; areas = pool.length;
          pool.forEach(function (row) { total += row.gdp_native || 0; });
        } else {
          pool = rows.filter(function (row) {
            return row.year === year && row[column] !== null && row[column] !== undefined;
          });
          if (keyword) { pool = pool.filter(function (row) { return matchesKeyword(row, keyword); }); }
          // 注意：在线版的合计口径不带关键词筛选，这里保持一致
          var yearRows = rows.filter(function (row) { return row.year === year; });
          total = 0; areas = yearRows.length;
          yearRows.forEach(function (row) { total += row.gdp_native || 0; });
        }
        var fields = mode === "latest" ? LATEST_FIELDS : RANK_FIELDS;
        var items = sortedBy(pool, column, "region_code").slice(0, limit).map(function (row) {
          return pick(row, fields);
        });
        return { economy: economy, level: level, year: year, mode: mode, metric: metric,
                 level_name: LEVEL_NAMES[level] || level,
                 currency: items.length ? items[0].currency : "CNY",
                 total: total, areas: areas, items: items,
                 year_distribution: regionModeYears(economy, level) };
      });
    },

    "/api/region/children": function (params) {
      var parent = params.parent;
      if (!parent) { throw new Error("缺少 parent 参数"); }
      var year = params.year ? Number(params.year) : null;
      var limit = clamp(params.limit, 20, 5, 100);
      // 下钻的父级可能是任一经济体/层级，按需加载：先看索引，找不到再逐个经济体试
      var economies = Object.keys(store.meta.levels);
      var levelsOf = [];
      economies.forEach(function (economy) {
        store.meta.levels[economy].forEach(function (item) { levelsOf.push([economy, item.level]); });
      });
      var parents = store.meta.parents || {};
      var target = parents[parent] || null;             // {"CHN": "city", ...}
      var jobs = target ? [[Object.keys(target)[0], target[Object.keys(target)[0]]]]
                        : levelsOf;
      return Promise.all(jobs.map(function (job) { return loadRegion(job[0], job[1]); }))
        .then(function (packs) {
          var all = [];
          packs.forEach(function (rows) {
            rows.forEach(function (row) {
              if (row.parent_code === parent && row.gdp_native !== null && row.gdp_native !== undefined) {
                all.push(row);
              }
            });
          });
          if (!all.length) { return { parent: parent, year: year, currency: "CNY", items: [] }; }
          var useYear = year;
          if (!useYear) {
            var newest = Math.max.apply(null, all.map(function (row) { return row.year; }));
            useYear = newest;
          }
          var items = all.filter(function (row) { return row.year === useYear; })
                         .sort(function (a, b) {
                           if (b.gdp_native !== a.gdp_native) { return b.gdp_native - a.gdp_native; }
                           return a.region_code < b.region_code ? -1 : (a.region_code > b.region_code ? 1 : 0);
                         })
                         .slice(0, limit)
                         .map(function (row) { return pick(row, CHILD_FIELDS); });
          return { parent: parent, year: items.length ? items[0].year : useYear,
                   currency: items.length ? items[0].currency : "CNY", items: items };
        });
    },

    "/api/region/compare": function (params) {
      var top = clamp(params.top, 6, 3, 12);
      var jobs = [loadRegion("CHN", "province"), loadRegion("USA", "state")];
      return Promise.all(jobs).then(function (packs) {
        var result = {};
        [["CHN", packs[0]], ["USA", packs[1]]].forEach(function (pair) {
          var economy = pair[0], rows = pair[1];
          var latestByCode = {};
          rows.forEach(function (row) {
            var key = row.region_code;
            if (!latestByCode[key] || row.year > latestByCode[key].year) { latestByCode[key] = row; }
          });
          var pool = Object.keys(latestByCode).map(function (key) { return latestByCode[key]; })
                            .filter(function (row) { return row.gdp_native !== null && row.gdp_native !== undefined; });
          var year = pool.length ? Math.max.apply(null, pool.map(function (row) { return row.year; })) : null;
          var items = sortedBy(pool.filter(function (row) { return row.year === year; }), "gdp_native")
            .slice(0, top)
            .map(function (row) {
              return { name: row.region_name, gdp_usd: row.gdp_usd,
                       gdp_native: row.gdp_native, currency: row.currency };
            });
          result[economy] = { year: year, items: items };
        });
        return result;
      });
    },

    "/api/crawl/status": function () {
      return { running: false, stage: "", message: "静态演示站点为只读快照，未启用采集功能",
               done: 0, total: 0, percent: 0.0, results: [], error: null };
    },

    "/api/crawl/history": function () { return { items: store.crawl.items || [] }; },

    "/api/export/csv": function () { return { total: 0, items: [] }; }
  };

  // ---- 区域相关的小工具 ----
  function economyOf(params) {
    var code = (params.economy || "CHN").toUpperCase();
    return ECONOMY_NAMES[code] ? code : "CHN";
  }

  // 区域接口返回的字段集要与 DAO 的 SELECT 严格一致：多一个字段也算不一致
  var RANK_FIELDS = ["region_code", "region_name", "parent_code", "parent_name", "year",
                     "gdp_native", "increment_native", "growth_rate", "population", "currency",
                     "gdp_usd", "per_capita_native", "source"];
  var LATEST_FIELDS = ["economy", "level"].concat(RANK_FIELDS);
  var CHILD_FIELDS = ["economy", "level", "region_code", "region_name", "parent_name", "year",
                      "gdp_native", "increment_native", "growth_rate", "population", "currency",
                      "gdp_usd", "per_capita_native", "source"];

  function pick(row, fields) {
    var item = {};
    fields.forEach(function (field) { item[field] = row[field]; });
    return item;
  }

  function matchesKeyword(row, keyword) {
    return like(row.region_name, keyword) || like(row.parent_name, keyword);
  }

  function regionYears(economy, level) {
    var levels = store.meta.levels[economy] || [];
    for (var i = 0; i < levels.length; i++) {
      if (levels[i].level === level) { return levels[i].years || []; }
    }
    return [];
  }

  function regionModeYears(economy, level) {
    var levels = store.meta.levels[economy] || [];
    for (var i = 0; i < levels.length; i++) {
      if (levels[i].level === level) { return levels[i].mode_years || []; }
    }
    return [];
  }

  function regionLevelsPayload(economy) {
    var levels = store.meta.levels[economy] || [];
    var years = {};
    levels.forEach(function (item) { years[item.level] = item.years || []; });
    // 返回结构对齐 DAO 的 region_levels()：多带的 years/mode_years 只供内部使用
    var public_levels = levels.map(function (item) {
      return { level: item.level, areas: item.areas, records: item.records,
               latest_year: item.latest_year };
    });
    return { economy: economy, levels: public_levels, years: years };
  }

  function codesOf(params, defaults, limit) {
    var codes = params.codes;
    if (!codes) { codes = defaults.slice(); } else { codes = codes.split(","); }
    codes = codes.map(function (code) { return String(code).trim().toUpperCase(); })
                 .filter(function (code) { return !!code; });
    return codes.slice(0, limit || 8);
  }

  function clamp(value, fallback, low, high) {
    var number = parseInt(value, 10);
    if (isNaN(number)) { number = fallback; }
    if (low !== undefined && number < low) { number = low; }
    if (high !== undefined && number > high) { number = high; }
    return number;
  }

  // ==================================================================
  // 路由：接管 GDP.getJSON
  // ==================================================================
  var originalGetJSON = GDP.getJSON;

  function parseQuery(url) {
    var index = url.indexOf("?");
    var params = {};
    if (index < 0) { return params; }
    url.slice(index + 1).split("&").forEach(function (pair) {
      if (!pair) { return; }
      var parts = pair.split("=");
      var key = decodeURIComponent(parts[0]);
      var value = decodeURIComponent((parts[1] || "").replace(/\+/g, " "));
      if (key === "codes" && params.codes) { params.codes += "," + value; }
      else { params[key] = value; }
    });
    return params;
  }

  // 参数里出现的“下钻父级”索引：导出时写在 meta.json 里，避免为了找父级加载所有数据文件
  GDP.getJSON = function (url) {
    var path = url.split("?")[0];
    var handler = api[path];
    if (!handler) { return originalGetJSON(url); }         // 未覆盖的接口交回原实现
    var params = parseQuery(url);
    return prepare().then(function () {
      return handler(params);
    }).catch(function (error) {
      return Promise.reject(new Error("静态数据加载失败：" + error.message));
    });
  };

  // ==================================================================
  // 页面适配：让静态站上的控件仍然可用
  // ==================================================================
  function queryParams() {
    var params = {};
    window.location.search.replace(/^\?/, "").split("&").forEach(function (pair) {
      if (!pair) { return; }
      var parts = pair.split("=");
      params[decodeURIComponent(parts[0])] = decodeURIComponent((parts[1] || "").replace(/\+/g, " "));
    });
    return params;
  }

  function setURL(params) {
    var pieces = [];
    Object.keys(params).forEach(function (key) {
      if (params[key] !== "" && params[key] !== null && params[key] !== undefined) {
        pieces.push(encodeURIComponent(key) + "=" + encodeURIComponent(params[key]));
      }
    });
    var search = pieces.length ? "?" + pieces.join("&") : "";
    window.history.replaceState(null, "", window.location.pathname + search);
  }

  function note(text) {
    var box = document.createElement("p");
    box.className = "muted";
    box.style.marginTop = "10px";
    box.innerHTML = text;
    return box;
  }

  // ---- 通用：控件按地址栏参数回填（趋势/对比/份额/数据集等页）----
  function hydrateControls(scope) {
    var params = queryParams();
    var root = scope || document;
    root.querySelectorAll("select[name], input[name]").forEach(function (control) {
      var name = control.getAttribute("name");
      if (!(name in params)) { return; }
      if (control.type === "checkbox") {
        control.checked = String(params[name]).split(",").indexOf(control.value) >= 0;
      } else {
        control.value = params[name];
      }
    });
  }

  // ---- 排行榜页：表格改为前端重画，年份/指标/每页条数照旧可用 ----
  function setupRankPage() {
    var box = document.getElementById("chart-rank");
    if (!box) { return; }
    var form = document.querySelector(".toolbar");
    var table = document.querySelector("#table tbody") ? document.querySelector("#table") : null;
    var params = queryParams();
    var metric = params.metric === "per_capita" ? "per_capita" : "gdp";
    var year = params.year ? Number(params.year) : null;
    var limit = params.limit ? Number(params.limit) : 15;

    var worldTotal = 0;      // 由 /api/share 提供（/api/rank 本身不返回全球合计）

    function rerun() {
      var current = queryParams();
      var metricNow = current.metric === "per_capita" ? "per_capita" : "gdp";
      var yearNow = current.year ? Number(current.year) : null;
      var limitNow = current.limit ? Number(current.limit) : 15;
      var rankURL = "/api/rank?metric=" + metricNow + "&limit=" + limitNow +
                    (yearNow ? "&year=" + yearNow : "");
      var totalURL = "/api/share?top=5" + (yearNow ? "&year=" + yearNow : "");
      Promise.all([GDP.getJSON(rankURL), GDP.getJSON(totalURL)])
        .then(function (both) {
          worldTotal = both[1].total || 0;
          render(both[0], metricNow);
        })
        .catch(function (error) { GDP.showError("chart-rank", error.message); });
    }

    function render(data, metricNow) {
      GDP.drawRankBar("chart-rank", data.items.map(function (item) {
        return { name: item.name_cn, value: item.value };
      }));
      if (!table) { return; }
      var body = table.querySelector("tbody");
      var rows = data.items.map(function (item, index) {
        var place = index + 1;
        var ratio = (worldTotal && metricNow === "gdp")
          ? (item.value / worldTotal * 100).toFixed(2) + "%" : "-";
        var value = metricNow === "gdp" ? GDP.fmtUSD(item.value) : GDP.fmtNum(item.value, 0) + " 美元";
        return '<tr class="' + (place <= 3 ? "top" + place : "") + '">' +
          '<td><span class="rank-no">' + place + "</span></td>" +
          "<td><b>" + item.name_cn + '</b> <span class="tag">' + item.code + "</span></td>" +
          "<td>" + (item.region || "") + "</td>" +
          "<td>" + (item.income_level || "-") + "</td>" +
          '<td class="num">' + value + "</td>" +
          '<td class="num">' + ratio + "</td></tr>";
      }).join("");
      body.innerHTML = rows || '<tr><td colspan="6">该年份没有数据</td></tr>';
      var hint = table.querySelector(".panel-head .hint");
      if (hint) { hint.textContent = "共 " + data.items.length + " 条"; }
      var head = table.querySelector("thead th.num");
      if (head) { head.textContent = METRIC_NAMES[metricNow] || "数值"; }
    }

    if (form) {
      form.addEventListener("change", function (event) {
        if (event.target.name === "year" || event.target.name === "limit") {
          var params2 = queryParams();
          params2.year = event.target.name === "year" ? event.target.value : params2.year;
          params2.limit = event.target.name === "limit" ? event.target.value : params2.limit;
          setURL(params2);
          rerun();
        }
      });
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        // 指标是提交按钮：取触发提交的那个按钮的值
        var submitter = event.submitter;
        var params2 = queryParams();
        if (submitter && submitter.name === "metric") { params2.metric = submitter.value; }
        var yearBox = form.querySelector('select[name="year"]');
        if (yearBox) { params2.year = yearBox.value; }
        var limitBox = form.querySelector('select[name="limit"]');
        if (limitBox) { params2.limit = limitBox.value; }
        setURL(params2);
        rerun();
      });
    }
    hydrateControls(document);
    if (metric && year) { rerun(); }
  }

  // ---- 数据集页：表格与分页改为前端重画 ----
  function setupDatasetPage() {
    var table = document.querySelector("table.data");
    if (!table || !document.querySelector('select[name="size"]')) { return; }
    var form = table.closest(".panel").querySelector("form") || document.querySelector("form.toolbar");
    var wrap = table.closest(".table-wrap");
    var pager = document.querySelector(".pager");
    var offset = store.meta.counts;

    function current() {
      var params = queryParams();
      return {
        year: params.year || "", country: params.country || "",
        metric: params.metric === "per_capita" ? "per_capita" : "gdp",
        size: params.size || "20", page: Math.max(1, parseInt(params.page || "1", 10))
      };
    }

    function rerun() {
      var state = current();
      GDP.getJSON("/api/dataset?year=" + encodeURIComponent(state.year) +
                  "&country=" + encodeURIComponent(state.country) +
                  "&metric=" + state.metric + "&size=" + state.size + "&page=" + state.page)
        .then(function (data) { render(data, state); })
        .catch(function (error) {
          table.querySelector("tbody").innerHTML =
            '<tr><td colspan="7">' + error.message + "</td></tr>";
        });
    }

    function render(data, state) {
      var body = table.querySelector("tbody");
      body.innerHTML = data.items.map(function (item) {
        return "<tr>" +
          '<td><span class="tag">' + item.code + "</span></td>" +
          "<td><b>" + (item.name_cn || "-") + "</b></td>" +
          "<td>" + (item.region || "-") + "</td>" +
          "<td>" + (item.income_level || "-") + "</td>" +
          '<td class="num">' + item.year + "</td>" +
          '<td class="num">' + GDP.fmtUSD(item.gdp_usd) + "</td>" +
          '<td class="num">' + GDP.fmtNum(item.gdp_per_capita_usd, 0) + " 美元</td></tr>";
      }).join("") || '<tr><td colspan="7">没有符合条件的记录，换个筛选条件试试</td></tr>';

      var pages = Math.max(1, Math.ceil(data.total / Number(state.size)));
      var panel = table.closest(".panel");
      var hint = panel.querySelector(".panel-head .hint");
      if (hint) {
        hint.textContent = "共 " + GDP.fmtNum(data.total, 0) + " 条符合条件（已排除“世界/欧盟”等区域汇总项与缺值为空的记录），第 " +
          Math.min(state.page, pages) + "/" + pages + " 页";
      }
      if (pager) {
        pager.innerHTML =
          (state.page > 1 ? '<button class="btn ghost" data-page="' + (state.page - 1) + '">上一页</button>' : "") +
          (state.page < pages ? '<button class="btn ghost" data-page="' + (state.page + 1) + '">下一页</button>' : "") +
          '<span class="spacer"></span><span class="info">第 ' + Math.min(state.page, pages) + " / " + pages +
          " 页 · 共 " + GDP.fmtNum(data.total, 0) + " 条 · 每页 " + state.size + " 条</span>";
        pager.querySelectorAll("button[data-page]").forEach(function (button) {
          button.addEventListener("click", function () {
            var params = queryParams();
            params.page = button.getAttribute("data-page");
            setURL(params);
            rerun();
          });
        });
      }
      if (!wrap) { return; }
    }

    if (form) {
      form.addEventListener("change", function () {
        var params = queryParams();
        params.year = form.querySelector('select[name="year"]').value;
        params.country = form.querySelector('input[name="country"]').value;
        params.size = form.querySelector('select[name="size"]').value;
        params.page = "1";
        setURL(params);
        rerun();
      });
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var submitter = event.submitter;
        var params = queryParams();
        params.year = form.querySelector('select[name="year"]').value;
        params.country = form.querySelector('input[name="country"]').value;
        params.size = form.querySelector('select[name="size"]').value;
        params.page = "1";
        if (submitter && submitter.name === "metric") { params.metric = submitter.value; }
        setURL(params);
        rerun();
      });
      // 导出按钮指向静态数据文件（完整数据集）
      form.querySelectorAll('a[href*="export/csv"]').forEach(function (link) {
        link.setAttribute("href", DATA_DIR + "dataset/gdp_annual.csv");
        link.setAttribute("title", "静态站点提供完整数据集下载（在线版可按当前筛选导出）");
        link.textContent = "下载完整数据集 CSV";
      });
    }
    hydrateControls(document);
    rerun();
  }

  // ---- 区域页：表单改为跳转到预生成的视图，关键词改为筛当前表格 ----
  function setupRegionPage() {
    var form = document.getElementById("region-form");
    if (!form) { return; }
    var views = (store.meta.views || []);

    /** 年份归一化：null 与空值都表示“各区域最新可得” */
    function normalizeYear(value) {
      return (value === null || value === undefined || value === "") ? "latest" : String(value);
    }

    function matchView(params) {
      var best = null;
      views.forEach(function (view) {
        if (view.economy !== params.economy || view.level !== params.level) { return; }
        var score = 1;
        score += view.mode === params.mode ? 3 : -1;
        if (normalizeYear(view.year) === normalizeYear(params.year)) { score += 2; }
        if (view.metric === params.metric) { score += 2; }
        if (String(view.limit) === String(params.limit)) { score += 2; }
        if (!best || score > best.score) { best = { score: score, view: view }; }
      });
      return best ? best.view : null;
    }

    function hint(message) {
      var box = document.getElementById("static-route-hint");
      if (!box) {
        box = document.createElement("p");
        box.id = "static-route-hint";
        box.className = "muted";
        box.style.color = "#B23A3A";
        box.style.marginTop = "8px";
        form.insertAdjacentElement("afterend", box);
      }
      box.textContent = message;
    }

    function route() {
      var economy = form.querySelector('select[name="economy"]').value;
      var level = form.querySelector('select[name="level"]').value;
      // 静态站切换经济体时不会重新渲染层级下拉框，这里按该经济体的层级清单回退
      // （在线版的做法是“层级不属于该经济体就取第一个”，两者行为保持一致）
      var levels = store.meta.levels[economy] || [];
      if (levels.length && !levels.some(function (item) { return item.level === level; })) {
        level = levels[0].level;
      }
      var params = {
        economy: economy,
        level: level,
        mode: form.querySelector('select[name="mode"]').value,
        metric: (form.querySelector(".segmented button.on") || {}).value || "gdp",
        limit: form.querySelector('select[name="limit"]').value,
        year: (form.querySelector('select[name="year"]') || {}).value || ""
      };
      var view = matchView(params);
      if (!view) {
        hint("静态演示站点只预生成了常用的视图组合（见上方快捷视图）：" +
             (store.meta.economy_names[economy] || economy) + " · " + (LEVEL_NAMES[level] || level) +
             " 暂无该组合的页面，请在本地版或在线版查看。");
        return;
      }
      window.location.href = view.file;
    }

    // 覆盖页面里的 submitForm()，把“提交表单”变成“切换到对应视图”
    window.submitForm = route;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      route();
    });

    // 关键词：静态站点没有后端筛选，改成筛当前表格里已列出的行
    var keywordBox = form.querySelector('input[name="keyword"]');
    if (keywordBox) {
      keywordBox.value = "";
      keywordBox.placeholder = "静态版：筛选当前表格";
      var table = document.querySelector("table.data");
      var rows = table ? Array.prototype.slice.call(table.querySelectorAll("tbody tr")) : [];
      keywordBox.addEventListener("input", function () {
        var keyword = keywordBox.value.trim().toLowerCase();
        var shown = 0;
        rows.forEach(function (row) {
          var text = row.textContent.toLowerCase();
          var hit = !keyword || text.indexOf(keyword) >= 0;
          row.style.display = hit ? "" : "none";
          if (hit) { shown += 1; }
        });
        var hint = table.closest(".panel").querySelector(".panel-head .hint");
        if (hint) {
          hint.textContent = keyword
            ? "静态版：当前表格中匹配“" + keywordBox.value.trim() + "”的有 " + shown + " 行（完整筛选请用本地版）"
            : "共 " + rows.length + " 行";
        }
      });
    }

    // 县级数据在静态站里只导出了最新一年，页面如实标注，避免读者误以为缺少历史年份
    if (store.meta.county_latest_only) {
      var levelSelect = form.querySelector('select[name="level"]');
      var tableBox = document.querySelector("table.data");
      if (levelSelect && levelSelect.value === "county" && tableBox) {
        var panel = tableBox.closest(".panel");
        if (panel && !panel.querySelector(".static-county-note")) {
          var noteBox = note(
            "静态演示站点：美国县级数据只导出了<b>每个县的最新一年</b>（完整 24 年共 7.4 万行见本地版与在线版），" +
            "因此县级视图仅提供「各区域最新可得」口径。");
          noteBox.className = "muted static-county-note";
          panel.querySelector(".panel-head").insertAdjacentElement("afterend", noteBox);
        }
      }
    }

    // 导出按钮指向静态数据文件
    form.querySelectorAll('a[href*="region/export.csv"]').forEach(function (link) {
      var economy = form.querySelector('select[name="economy"]').value;
      var level = form.querySelector('select[name="level"]').value;
      link.setAttribute("href", DATA_DIR + "dataset/region-export-" + economy + "-" + level + ".csv");
      link.setAttribute("title", "静态站点提供该层级的完整 CSV（在线版可按当前筛选导出）");
    });
  }

  // ---- 趋势/对比/份额/中国季度：控件按地址栏回填即可 ----
  function setupGenericPage() {
    hydrateControls(document);
  }

  // ==================================================================
  // 启动
  // ==================================================================
  prepare().then(function () {
    setupRegionPage();
    setupRankPage();
    setupDatasetPage();
    setupGenericPage();
  }).catch(function (error) {
    console.error(error);
    document.querySelectorAll(".chart").forEach(function (box) {
      GDP.showError(box.id, "静态数据加载失败：" + error.message);
    });
  });
})();