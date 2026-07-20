(function () {
  "use strict";

  var HISTORY_PROVIDER = window.CARS_FILTER_HISTORY_PROVIDER || "worker";
  var HISTORY_API = window.CARS_FILTER_HISTORY_API || "/api/filter-history";
  var GITHUB_HISTORY = window.CARS_GITHUB_HISTORY || null;
  var DEFAULT_SYNC_ID = window.CARS_DEFAULT_FILTER_SYNC_ID || "";
  var STORAGE_SYNC_KEY = "phones_filter_sync_id";
  var STORAGE_HISTORY_KEY = "phones_filter_history_cache";
  var STORAGE_GITHUB_TOKEN_KEY = "phones_filter_github_token";

  var CORE_COLUMNS = ["型号","品牌","上市时间","价格","验证状态","数据来源","处理器","内存","存储","屏幕","屏占比","电池","机身厚度","机身重量","指纹识别","面部识别","网络类型","NFC","连接与共享","机身接口","有线充电","无线充电","快充协议","交叉验证差异","散热","广角","Geekbench6单核","是否可解BL锁","root或越狱"];

  var SAMPLE_ROWS = [
    {
      "数据来源": "示例",
      "品牌": "示例品牌",
      "型号": "等待 GitHub Pages 发布最新数据",
      "上市时间": "2026",
      "手机类型": "5G手机",
      "价格": "3999",
      "处理器": "骁龙8 Gen3",
      "电池": "5000mAh",
      "指纹识别": "支持",
      "面部识别": "支持",
      "NFC": "支持",
      "验证状态": "三源一致"
    }
  ];

  var DEFAULT_RANGE_FILTERS = {
    price: { min: "", max: "" }
  };
  var DEFAULT_FEATURE_FILTERS = {
    nfc: true,
    face_id: true,
    fingerprint: true
  };

  var fallbackConfig = {
    defaultDataset: "latest",
    hiddenByDefault: ["数据来源"],
    dropIfUniformPositive: [],
    defaultVisibleColumns: CORE_COLUMNS,
    conditions: []
  };

  var state = {
    manifest: null,
    config: fallbackConfig,
    rows: [],
    columns: [],
    visibleColumns: new Set(),
    columnFilters: {},
    rangeFilters: Object.assign({}, DEFAULT_RANGE_FILTERS),
    featureFilters: Object.assign({}, DEFAULT_FEATURE_FILTERS),
    search: "",
    brand: "",
    series: "",
    sortField: "",
    sortDir: "asc",
    sortLevels: [],
    mode: "center",
    cardLimit: 24,
    expandedSeries: new Set(),
    seriesViewSignature: "",
    page: 1,
    pageSize: 100,
    columnSearch: "",
    composing: false,
    syncId: "",
    githubToken: "",
    histories: []
  };

  var els = {
    dataMeta: document.getElementById("dataMeta"),
    globalSearch: document.getElementById("globalSearch"),
    resetFilters: document.getElementById("resetFilters"),
    saveHistory: document.getElementById("saveHistory"),
    exportCsv: document.getElementById("exportCsv"),
    exportJson: document.getElementById("exportJson"),
    visibleCount: document.getElementById("visibleCount"),
    totalCount: document.getElementById("totalCount"),
    columnCount: document.getElementById("columnCount"),
    verifiedCount: document.getElementById("verifiedCount"),
    zolCount: document.getElementById("zolCount"),
    pconlineCount: document.getElementById("pconlineCount"),
    cnmoCount: document.getElementById("cnmoCount"),
    brandFilter: document.getElementById("brandFilter"),
    seriesFilter: document.getElementById("seriesFilter"),
    pageSize: document.getElementById("pageSize"),
    tableHead: document.getElementById("tableHead"),
    tableBody: document.getElementById("tableBody"),
    emptyState: document.getElementById("emptyState"),
    prevPage: document.getElementById("prevPage"),
    nextPage: document.getElementById("nextPage"),
    pageInfo: document.getElementById("pageInfo"),
    pageJump: document.getElementById("pageJump"),
    goPage: document.getElementById("goPage"),
    conditionList: document.getElementById("conditionList"),
    fieldSelect: document.getElementById("fieldSelect"),
    fieldOperator: document.getElementById("fieldOperator"),
    fieldValue: document.getElementById("fieldValue"),
    applyFieldFilter: document.getElementById("applyFieldFilter"),
    activeFilters: document.getElementById("activeFilters"),
    showCoreColumns: document.getElementById("showCoreColumns"),
    showAllColumns: document.getElementById("showAllColumns"),
    columnSearch: document.getElementById("columnSearch"),
    columnList: document.getElementById("columnList"),
    historySyncId: document.getElementById("historySyncId"),
    githubToken: document.getElementById("githubToken"),
    copySyncId: document.getElementById("copySyncId"),
    loadHistory: document.getElementById("loadHistory"),
    saveGithubToken: document.getElementById("saveGithubToken"),
    clearGithubToken: document.getElementById("clearGithubToken"),
    historyStatus: document.getElementById("historyStatus"),
    historyList: document.getElementById("historyList"),
    downloadList: document.getElementById("downloadList"),
    centerMode: document.getElementById("centerMode"),
    tableMode: document.getElementById("tableMode"),
    filterCenter: document.getElementById("filterCenter"),
    tableRegion: document.getElementById("tableRegion"),
    centerBrandFilter: document.getElementById("centerBrandFilter"),
    centerSeriesFilter: document.getElementById("centerSeriesFilter"),
    centerConditionList: document.getElementById("centerConditionList"),
    selectedTags: document.getElementById("selectedTags"),
    cardList: document.getElementById("cardList"),
    centerVisibleCount: document.getElementById("centerVisibleCount"),
    loadMoreCards: document.getElementById("loadMoreCards"),
    customSortLevels: document.getElementById("customSortLevels"),
    addSortLevel: document.getElementById("addSortLevel"),
    clearSortLevels: document.getElementById("clearSortLevels")
  };

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status + " " + url);
      }
      return response.json();
    });
  }

  function normalizeText(value) {
    return String(value == null ? "" : value).toLowerCase();
  }

  function cleanText(value) {
    return String(value == null ? "" : value).replace(/\s+/g, "").toLowerCase();
  }

  function cloneDefaultRangeFilters() {
    return JSON.parse(JSON.stringify(DEFAULT_RANGE_FILTERS));
  }

  function cloneDefaultFeatureFilters() {
    return Object.assign({}, DEFAULT_FEATURE_FILTERS);
  }

  function firstNumber(value) {
    var match = String(value == null ? "" : value).match(/\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function uniqueValues(rows, field) {
    return Array.from(new Set(rows.map(function (row) {
      return String(row[field] || "").trim();
    }).filter(Boolean))).sort(function (a, b) {
      return a.localeCompare(b, "zh-Hans", { numeric: true });
    });
  }

  function hasPositiveValue(value) {
    var text = String(value == null ? "" : value).trim();
    if (!text || text === "-") {
      return false;
    }
    return ["无", "不支持", "否", "没有", "未配备", "不提供", "0", "0.0"].indexOf(text) === -1;
  }

  function atomicSources(value) {
    var text = String(value == null ? "" : value).trim();
    var sources = new Set();
    var knownSources = ["中关村在线", "太平洋电脑网", "CNMO"];
    text.split(/[+＋/／|、,，;；]+/).forEach(function (part) {
      var item = part.trim();
      var recognized = false;
      knownSources.forEach(function (source) {
        if (item.indexOf(source) !== -1) {
          sources.add(source);
          recognized = true;
        }
      });
      if (item && !recognized) {
        sources.add(item);
      }
    });
    return Array.from(sources);
  }

  function rowHasSource(row, source) {
    return String(row["数据来源"] || "").indexOf(source) !== -1;
  }

  function baseModelName(model) {
    return String(model || "").replace(/[（(][^）)]*[）)]/g, "").trim();
  }

  function modelIdentity(row) {
    var brand = String(row["品牌"] || row["brand"] || "").trim();
    var model = String(row["型号"] || "").trim();
    var base = baseModelName(model);
    if (base) {
      return { key: "model|" + brand + "|" + base, name: base };
    }
    return {
      key: "model|" + brand + "|" + model,
      name: model || "未命名型号"
    };
  }

  function groupRowsByModel(rows) {
    var groups = [];
    var groupMap = new Map();
    rows.forEach(function (row) {
      var identity = modelIdentity(row);
      var group = groupMap.get(identity.key);
      if (!group) {
        group = {
          key: identity.key,
          name: identity.name,
          rows: [],
          representative: row,
          price: null,
          order: groups.length
        };
        groupMap.set(identity.key, group);
        groups.push(group);
      }
      group.rows.push(row);
    });

    var levels = activeSortLevels();
    var priceLevel = levels.length && isPriceField(levels[0].field) ? levels[0] : null;
    if (!priceLevel) {
      return groups;
    }

    groups.forEach(function (group) {
      group.rows.forEach(function (row) {
        var price = validPrice(row, priceLevel.field);
        if (price === null) {
          return;
        }
        var better = group.price === null ||
          (priceLevel.dir === "desc" ? price > group.price : price < group.price);
        if (better) {
          group.price = price;
          group.representative = row;
        }
      });
    });

    return groups.sort(function (a, b) {
      if (a.price === null || b.price === null) {
        if (a.price === null && b.price !== null) { return 1; }
        if (a.price !== null && b.price === null) { return -1; }
      } else if (a.price !== b.price) {
        return priceLevel.dir === "desc" ? b.price - a.price : a.price - b.price;
      }
      for (var i = 1; i < levels.length; i += 1) {
        var result = compareRowsByLevel(a.representative, b.representative, levels[i]);
        if (result !== 0) {
          return result;
        }
      }
      var nameResult = a.name.localeCompare(b.name, "zh-Hans", { numeric: true });
      return nameResult || a.key.localeCompare(b.key, "zh-Hans", { numeric: true }) || a.order - b.order;
    });
  }

  function isDimensionColumn(column) {
    return false;
  }

  function shouldHideColumn(column, rows) {
    var hidden = state.config.hiddenByDefault || [];
    var dropUniform = state.config.dropIfUniformPositive || [];
    if (hidden.indexOf(column) !== -1) {
      return true;
    }
    if (dropUniform.indexOf(column) !== -1) {
      var values = rows.map(function (row) { return row[column]; }).filter(function (value) {
        return value != null && value !== "";
      });
      return values.length > 0 && values.every(hasPositiveValue);
    }
    return false;
  }

  function buildColumns(rows) {
    var seen = new Set();
    var columns = [];
    (state.config.defaultVisibleColumns || []).forEach(function (column) {
      if (rows.some(function (row) { return Object.prototype.hasOwnProperty.call(row, column); }) && !shouldHideColumn(column, rows)) {
        seen.add(column);
        columns.push(column);
      }
    });
    rows.forEach(function (row) {
      Object.keys(row).forEach(function (column) {
        if (shouldHideColumn(column, rows) || seen.has(column)) {
          return;
        }
        seen.add(column);
        columns.push(column);
      });
    });
    return columns;
  }

  function conditionMatches(row, condition) {
    if (condition.type === "range") {
      var filter = state.rangeFilters[condition.id] || {};
      var rowValue = firstNumber(row[condition.field]);
      if (rowValue == null) {
        return false;
      }
      if (filter.min !== "" && filter.min != null && rowValue < Number(filter.min)) {
        return false;
      }
      if (filter.max !== "" && filter.max != null && rowValue > Number(filter.max)) {
        return false;
      }
      return true;
    }

    if (condition.type === "feature") {
      if (!state.featureFilters[condition.id]) {
        return true;
      }
      var fields = condition.fields || [];
      var keywords = condition.keywords || [];
      return Object.keys(row).some(function (key) {
        var val = row[key];
        if (!hasPositiveValue(val)) {
          return false;
        }
        var keyHit = fields.some(function (field) { return key.indexOf(field) !== -1 || field.indexOf(key) !== -1; });
        var valHit = keywords.some(function (keyword) { return String(val).indexOf(keyword) !== -1; });
        return condition.requireKeyword ? valHit : (keyHit || valHit);
      });
    }

    return true;
  }

  function rowMatchesDefaultRowType(row) {
    return true;
  }

  function parseCustomOrder(text) {
    return String(text || "").split(/[\n,，]+/).map(function (item) { return normalizeText(item.trim()); }).filter(Boolean);
  }

  function customOrderIndex(value, orderText) {
    var valueText = normalizeText(value);
    var order = parseCustomOrder(orderText);
    for (var i = 0; i < order.length; i += 1) {
      if (valueText.indexOf(order[i]) !== -1) {
        return i;
      }
    }
    return order.length;
  }

  function compareRowsByLevel(a, b, level) {
    var av = a[level.field];
    var bv = b[level.field];
    var order = parseCustomOrder(level.customOrder);
    var result;
    if (order.length) {
      result = customOrderIndex(av, level.customOrder) - customOrderIndex(bv, level.customOrder);
      if (result === 0) {
        result = String(av || "").localeCompare(String(bv || ""), "zh-Hans", { numeric: true });
      }
    } else {
      var an = firstNumber(av);
      var bn = firstNumber(bv);
      result = an !== null && bn !== null ? an - bn : String(av || "").localeCompare(String(bv || ""), "zh-Hans", { numeric: true });
    }
    return level.dir === "desc" ? -result : result;
  }

  function activeSortLevels() {
    var levels = (state.sortLevels || []).filter(function (level) { return level && level.field; });
    if (!levels.length && state.sortField) {
      levels = [{ field: state.sortField, dir: state.sortDir || "asc", customOrder: "" }];
    }
    return levels;
  }

  function sortRows(rows) {
    var levels = activeSortLevels();
    if (!levels.length) {
      return rows;
    }
    return rows.map(function (row, index) { return { row: row, index: index }; }).sort(function (a, b) {
      for (var i = 0; i < levels.length; i += 1) {
        var result = compareRowsByLevel(a.row, b.row, levels[i]);
        if (result !== 0) {
          return result;
        }
      }
      return a.index - b.index;
    }).map(function (item) { return item.row; });
  }

  function isPriceField(field) {
    return /(?:价格|售价|报价)/.test(String(field || ""));
  }

  function validPrice(row, field) {
    var value = firstNumber(row[field]);
    return value !== null && Number.isFinite(value) && value > 0 ? value : null;
  }

  function currentSeriesViewSignature() {
    return JSON.stringify({
      search: state.search,
      brand: state.brand,
      series: state.series,
      columnFilters: state.columnFilters,
      rangeFilters: state.rangeFilters,
      featureFilters: state.featureFilters,
      sortField: state.sortField,
      sortDir: state.sortDir,
      sortLevels: state.sortLevels
    });
  }

  function syncSeriesViewState() {
    var signature = currentSeriesViewSignature();
    if (signature !== state.seriesViewSignature) {
      state.expandedSeries.clear();
      state.cardLimit = 24;
      state.seriesViewSignature = signature;
    }
  }

  function getFilteredRows() {
    var rows = state.rows.slice();

    var search = normalizeText(state.search);

    if (state.source) {
      rows = rows.filter(function (row) { return String(row["数据来源"] || "").indexOf(state.source) !== -1; });
    }
    if (state.brand) {
      rows = rows.filter(function (row) { return (row["品牌"] || row["brand"]) === state.brand; });
    }
    if (state.series) {
      rows = rows.filter(function (row) { return baseModelName(row["型号"]) === state.series; });
    }
    if (search) {
      rows = rows.filter(function (row) {
        return Object.keys(row).some(function (key) {
          return normalizeText(row[key]).indexOf(search) !== -1 || normalizeText(key).indexOf(search) !== -1;
        });
      });
    }

    (state.config.conditions || []).forEach(function (condition) {
      var activeRange = state.rangeFilters[condition.id];
      var activeFeature = state.featureFilters[condition.id];
      if (condition.type === "range" && !activeRange) {
        return;
      }
      if (condition.type === "feature" && !activeFeature) {
        return;
      }
      rows = rows.filter(function (row) { return conditionMatches(row, condition); });
    });

    Object.keys(state.columnFilters).forEach(function (column) {
      var filter = state.columnFilters[column];
      if (!filter || filter.value === "") {
        return;
      }
      rows = rows.filter(function (row) {
        var text = normalizeText(row[column]);
        var value = normalizeText(filter.value);
        var number = firstNumber(row[column]);
        if (filter.operator === "contains") {
          return text.indexOf(value) !== -1;
        }
        if (number == null) {
          return false;
        }
        if (filter.operator === "gte") {
          return number >= Number(filter.value);
        }
        if (filter.operator === "lte") {
          return number <= Number(filter.value);
        }
        return filter.operator === "equals" ? text === value : text.indexOf(value) !== -1;
      });
    });

    return sortRows(rows);
  }

  function renderOptions(select, values, label) {
    select.textContent = "";
    var allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "全部" + label;
    select.appendChild(allOption);
    values.forEach(function (value) {
      var option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  function uniqueBaseModels(rows) {
    return Array.from(new Set(rows.map(function (row) {
      return baseModelName(row["型号"]);
    }).filter(Boolean))).sort(function (a, b) {
      return a.localeCompare(b, "zh-Hans", { numeric: true });
    });
  }

  function renderFilters() {
    if (els.brandFilter && els.seriesFilter) {
      renderOptions(els.brandFilter, uniqueValues(state.rows.map(function(r){ return r["品牌"] || r["brand"] || ""; }), "品牌"), "品牌");
      renderOptions(els.seriesFilter, uniqueBaseModels(state.brand ? state.rows.filter(function (row) {
        return (row["品牌"] || row["brand"]) === state.brand;
      }) : state.rows), "型号系列");
      els.brandFilter.value = state.brand;
      els.seriesFilter.value = state.series;
    }

    els.fieldSelect.textContent = "";
    state.columns.forEach(function (column) {
      var option = document.createElement("option");
      option.value = column;
      option.textContent = column;
      els.fieldSelect.appendChild(option);
    });
  }

  function renderConditions() {
    var fragment = document.createDocumentFragment();
    els.conditionList.textContent = "";
    (state.config.conditions || []).forEach(function (condition) {
      var item = document.createElement("div");
      item.className = "condition-item";
      item.dataset.conditionId = condition.id;

      var title = document.createElement("label");
      title.className = "condition-title";
      if (condition.type === "feature") {
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(state.featureFilters[condition.id]);
        checkbox.dataset.conditionId = condition.id;
        title.appendChild(checkbox);
      }
      var text = document.createElement("span");
      text.textContent = conditionTagLabel(condition);
      title.appendChild(text);
      item.appendChild(title);

      if (condition.type === "range") {
        var controls = document.createElement("div");
        controls.className = "range-controls";
        ["min", "max"].forEach(function (side) {
          var input = document.createElement("input");
          input.type = "number";
          input.inputMode = "decimal";
          input.placeholder = side === "min" ? "最小" : "最大";
          input.dataset.conditionId = condition.id;
          input.dataset.side = side;
          var active = state.rangeFilters[condition.id] || {};
          input.value = active[side] != null ? active[side] : (condition[side] != null ? condition[side] : "");
          controls.appendChild(input);
        });
        var button = document.createElement("button");
        button.type = "button";
        button.dataset.conditionId = condition.id;
        button.textContent = "筛选";
        controls.appendChild(button);
        item.appendChild(controls);
      }

      fragment.appendChild(item);
    });
    els.conditionList.appendChild(fragment);
  }

  function sortMark(column) {
    if (state.sortField !== column) {
      return "";
    }
    return state.sortDir === "asc" ? "↑" : "↓";
  }

  function renderTableHead() {
    var visibleColumns = state.columns.filter(function (column) { return state.visibleColumns.has(column); });
    els.tableHead.textContent = "";

    var titleRow = document.createElement("tr");
    visibleColumns.forEach(function (column) {
      var th = document.createElement("th");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sort-button";
      button.dataset.column = column;
      button.title = "按 " + column + " 排序";
      var name = document.createElement("span");
      name.textContent = column;
      var mark = document.createElement("span");
      mark.textContent = sortMark(column);
      button.appendChild(name);
      button.appendChild(mark);
      th.appendChild(button);
      titleRow.appendChild(th);
    });

    var filterRow = document.createElement("tr");
    filterRow.className = "filter-row";
    visibleColumns.forEach(function (column) {
      var th = document.createElement("th");
      var input = document.createElement("input");
      input.className = "filter-input";
      input.dataset.column = column;
      input.value = state.columnFilters[column] ? state.columnFilters[column].value : "";
      input.placeholder = "输入或点侧栏筛选";
      th.appendChild(input);
      filterRow.appendChild(th);
    });
    els.tableHead.appendChild(titleRow);
    els.tableHead.appendChild(filterRow);
  }

  function renderTableBody(rows) {
    var visibleColumns = state.columns.filter(function (column) { return state.visibleColumns.has(column); });
    var start = (state.page - 1) * state.pageSize;
    var pageRows = rows.slice(start, start + state.pageSize);
    els.tableBody.textContent = "";
    pageRows.forEach(function (row) {
      var tr = document.createElement("tr");
      visibleColumns.forEach(function (column) {
        var td = document.createElement("td");
        td.textContent = row[column] == null || row[column] === "" ? "-" : row[column];
        tr.appendChild(td);
      });
      els.tableBody.appendChild(tr);
    });
    els.emptyState.hidden = rows.length !== 0;
  }

  function renderColumnList() {
    var query = normalizeText(state.columnSearch);
    var fragment = document.createDocumentFragment();
    els.columnList.textContent = "";
    state.columns.filter(function (column) {
      return !query || normalizeText(column).indexOf(query) !== -1;
    }).forEach(function (column) {
      var label = document.createElement("label");
      var checkbox = document.createElement("input");
      var text = document.createElement("span");
      checkbox.type = "checkbox";
      checkbox.checked = state.visibleColumns.has(column);
      checkbox.dataset.column = column;
      text.textContent = column;
      label.appendChild(checkbox);
      label.appendChild(text);
      fragment.appendChild(label);
    });
    els.columnList.appendChild(fragment);
  }

  function filterLabel(column, filter) {
    if (!filter) {
      return "";
    }
    if (filter.operator === "contains") {
      return column + ": " + filter.value;
    }
    var symbol = filter.operator === "gte" ? "≥" : (filter.operator === "lte" ? "≤" : "=");
    return column + " " + symbol + " " + filter.value;
  }

  function renderActiveFilters() {
    els.activeFilters.textContent = "";
    Object.keys(state.columnFilters).forEach(function (column) {
      var filter = state.columnFilters[column];
      if (!filter || filter.value === "") {
        return;
      }
      var chip = document.createElement("span");
      chip.className = "filter-chip";
      chip.textContent = filterLabel(column, filter);
      var close = document.createElement("button");
      close.type = "button";
      close.dataset.column = column;
      close.textContent = "×";
      chip.appendChild(close);
      els.activeFilters.appendChild(chip);
    });
  }

  function renderDownloads() {
    var files = state.manifest && state.manifest.files ? state.manifest.files : {};
    var links = [["完整 JSON", files.latestJson], ["完整 CSV", files.latestCsv], ["默认筛选 JSON", files.filteredJson], ["默认筛选 CSV", files.filteredCsv]];
    els.downloadList.textContent = "";
    links.forEach(function (item) {
      if (!item[1]) {
        return;
      }
      var anchor = document.createElement("a");
      anchor.href = item[1];
      anchor.textContent = item[0];
      anchor.download = "";
      els.downloadList.appendChild(anchor);
    });
    if (!els.downloadList.children.length) {
      els.downloadList.textContent = "发布后会显示 Release 同款下载文件。";
    }
  }

  function renderHistory() {
    els.historySyncId.value = state.syncId;
    els.historyList.textContent = "";
    if (!state.histories.length) {
      els.historyList.textContent = "暂无筛选历史。";
      return;
    }
    state.histories.slice().reverse().forEach(function (item) {
      var row = document.createElement("div");
      row.className = "history-item";
      var button = document.createElement("button");
      button.type = "button";
      button.dataset.historyId = item.id;
      button.textContent = item.name || "未命名筛选";
      var meta = document.createElement("span");
      meta.textContent = (item.resultCount || 0) + " 台 · " + new Date(item.createdAt || Date.now()).toLocaleString("zh-CN");
      row.appendChild(button);
      row.appendChild(meta);
      els.historyList.appendChild(row);
    });
  }


  function renderMode() {
    var center = state.mode !== "table";
    els.filterCenter.hidden = !center;
    els.tableRegion.hidden = center;
    els.centerMode.className = center ? "segment active" : "segment";
    els.tableMode.className = center ? "segment" : "segment active";
  }

  function renderCenterFilters() {
    if (els.centerBrandFilter && els.centerSeriesFilter) {
      renderOptions(els.centerBrandFilter, uniqueValues(state.rows.map(function(r){ return r["品牌"] || r["brand"] || ""; }), "品牌"), "品牌");
      renderOptions(els.centerSeriesFilter, uniqueBaseModels(state.brand ? state.rows.filter(function (row) { return (row["品牌"] || row["brand"]) === state.brand; }) : state.rows), "型号系列");
      els.centerBrandFilter.value = state.brand;
      els.centerSeriesFilter.value = state.series;
    }
    els.centerConditionList.textContent = "";
    (state.config.conditions || []).forEach(function (condition) {
      var label = document.createElement("label");
      var input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.conditionId = condition.id;
      input.checked = condition.type === "feature" ? Boolean(state.featureFilters[condition.id]) : Boolean(state.rangeFilters[condition.id]);
      label.appendChild(input);
      label.appendChild(document.createTextNode(conditionTagLabel(condition)));
      els.centerConditionList.appendChild(label);
    });
  }

  function conditionTagLabel(condition) {
    if (condition.type !== "range") {
      return condition.label;
    }
    var filter = state.rangeFilters[condition.id] || {};
    var parts = [];
    if (filter.max !== "" && filter.max != null) {
      parts.push("≤" + filter.max);
    }
    if (filter.min !== "" && filter.min != null) {
      parts.push("≥" + filter.min);
    }
    return condition.label + (parts.length ? " " + parts.join(" ") : "");
  }

  function renderSelectedTags() {
    els.selectedTags.textContent = "";
    [["品牌", state.brand], ["型号系列", state.series]].forEach(function (item) {
      if (!item[1]) { return; }
      var tag = document.createElement("span");
      tag.textContent = item[0] + ": " + item[1];
      els.selectedTags.appendChild(tag);
    });
    (state.config.conditions || []).forEach(function (condition) {
      if (state.featureFilters[condition.id] || state.rangeFilters[condition.id]) {
        var tag = document.createElement("span");
        tag.textContent = conditionTagLabel(condition);
        els.selectedTags.appendChild(tag);
      }
    });
  }

  function appendCardMeta(container, row, fields) {
    fields.forEach(function (field) {
      if (row[field] && row[field] !== "-") {
        var chip = document.createElement("span");
        chip.textContent = field + ": " + row[field];
        container.appendChild(chip);
      }
    });
    var vs = row["验证状态"] || "";
    if (vs && vs !== "单源") {
      var badge = document.createElement("span");
      badge.className = "verified-badge multi-source";
      badge.textContent = vs;
      container.appendChild(badge);
    }
  }

  function renderCards(groups) {
    els.cardList.textContent = "";
    groups.slice(0, state.cardLimit).forEach(function (group, index) {
      var card = document.createElement("article");
      card.className = "series-card";
      var expanded = state.expandedSeries.has(group.key);
      var detailId = "series-models-" + index;
      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "series-card-toggle";
      toggle.dataset.seriesKey = group.key;
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-controls", detailId);
      var title = document.createElement("h3");
      title.textContent = group.name;
      var count = document.createElement("small");
      count.className = "series-match-count";
      count.textContent = group.rows.length + " 个版本符合条件";
      var indicator = document.createElement("span");
      indicator.className = "series-expand-indicator";
      indicator.setAttribute("aria-hidden", "true");
      indicator.textContent = expanded ? "收起" : "查看型号";
      toggle.appendChild(title);
      toggle.appendChild(count);
      toggle.appendChild(indicator);
      card.appendChild(toggle);

      var meta = document.createElement("div");
      meta.className = "card-meta";
      appendCardMeta(meta, group.representative, ["品牌", "手机类型", "价格", "处理器", "电池"]);
      card.appendChild(meta);

      if (expanded) {
        var details = document.createElement("div");
        details.className = "series-model-list";
        details.id = detailId;
        group.rows.forEach(function (row) {
          var model = document.createElement("div");
          model.className = "series-model-row";
          var modelTitle = document.createElement("h4");
          modelTitle.textContent = row["型号"] || "未命名型号";
          var modelMeta = document.createElement("div");
          modelMeta.className = "card-meta";
          appendCardMeta(modelMeta, row, ["上市时间", "手机类型", "价格", "处理器", "电池"]);
          model.appendChild(modelTitle);
          model.appendChild(modelMeta);
          details.appendChild(model);
        });
        card.appendChild(details);
      }
      els.cardList.appendChild(card);
    });
    els.loadMoreCards.hidden = groups.length <= state.cardLimit;
  }

  function renderCustomSortPanel() {
    if (!els.customSortLevels) { return; }
    els.customSortLevels.textContent = "";
    (state.sortLevels || []).forEach(function (level, index) {
      var row = document.createElement("div");
      row.className = "sort-level";
      row.dataset.index = String(index);
      row.innerHTML = '<label>字段<select data-role="field"></select></label><label>方向<select data-role="dir"><option value="asc">升序</option><option value="desc">降序</option></select></label><label>自定义关键字顺序<textarea data-role="customOrder" placeholder="旗舰, 中端, 入门"></textarea></label><button type="button" data-role="up">上移</button><button type="button" data-role="down">下移</button><button type="button" data-role="remove">删除</button>';
      var select = row.querySelectorAll ? row.querySelectorAll('select[data-role="field"]')[0] : null;
      if (select) {
        state.columns.forEach(function (column) { var option = document.createElement("option"); option.value = column; option.textContent = column; select.appendChild(option); });
        select.value = level.field || "";
      }
      var dir = row.querySelectorAll ? row.querySelectorAll('select[data-role="dir"]')[0] : null;
      if (dir) { dir.value = level.dir || "asc"; }
      var custom = row.querySelectorAll ? row.querySelectorAll('textarea[data-role="customOrder"]')[0] : null;
      if (custom) { custom.value = level.customOrder || ""; }
      els.customSortLevels.appendChild(row);
    });
  }

  function renderResultsOnly() {
    syncSeriesViewState();
    var filtered = getFilteredRows();
    var modelGroups = groupRowsByModel(filtered);
    var pageCount = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > pageCount) {
      state.page = pageCount;
    }
    els.visibleCount.textContent = String(filtered.length);
    els.totalCount.textContent = String(state.rows.length);
    els.columnCount.textContent = String(state.visibleColumns.size);
    var multiSourceCount = state.rows.filter(function (row) { return row["验证状态"] && row["验证状态"] !== "单源"; }).length;
    var singleCount = state.rows.filter(function (row) { return row["验证状态"] === "单源"; }).length;
    els.verifiedCount.textContent = String(multiSourceCount);
    els.verifiedCount.title = "多源核验: " + multiSourceCount + " | 单源: " + singleCount;
    els.zolCount.textContent = String(state.rows.filter(function (row) { return rowHasSource(row, "中关村在线"); }).length);
    els.pconlineCount.textContent = String(state.rows.filter(function (row) { return rowHasSource(row, "太平洋电脑网"); }).length);
    els.cnmoCount.textContent = String(state.rows.filter(function (row) { return rowHasSource(row, "CNMO"); }).length);
    els.pageInfo.textContent = "第 " + state.page + " / " + pageCount + " 页";
    els.pageJump.max = String(pageCount);
    els.pageJump.value = String(state.page);
    els.prevPage.disabled = state.page <= 1;
    els.nextPage.disabled = state.page >= pageCount;
    els.centerVisibleCount.textContent = String(modelGroups.length);
    renderCards(modelGroups);
    renderSelectedTags();
    renderTableBody(filtered);
    renderActiveFilters();
  }

  function renderEverything() {
    renderMode();
    renderFilters();
    renderCenterFilters();
    renderConditions();
    renderTableHead();
    renderColumnList();
    renderDownloads();
    renderHistory();
    renderCustomSortPanel();
    renderResultsOnly();
  }

  function csvEscape(value) {
    var text = String(value == null ? "" : value);
    return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function downloadBlob(name, type, content) {
    var blob = new Blob([content], { type: type });
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function exportCurrentCsv() {
    var rows = getFilteredRows();
    var columns = state.columns.filter(function (column) { return state.visibleColumns.has(column); });
    var lines = [columns.map(csvEscape).join(",")];
    rows.forEach(function (row) {
      lines.push(columns.map(function (column) { return csvEscape(row[column]); }).join(","));
    });
    downloadBlob("phone-config-current.csv", "text/csv;charset=utf-8", "\ufeff" + lines.join("\n"));
  }

  function exportCurrentJson() {
    downloadBlob("phone-config-current.json", "application/json;charset=utf-8", JSON.stringify(getFilteredRows(), null, 2));
  }

  function snapshotFilters() {
    return {
      search: state.search,
      brand: state.brand,
      series: state.series,
      columnFilters: state.columnFilters,
      rangeFilters: state.rangeFilters,
      featureFilters: state.featureFilters,
      sortField: state.sortField,
      sortDir: state.sortDir,
      sortLevels: state.sortLevels,
      mode: state.mode,
      visibleColumns: Array.from(state.visibleColumns)
    };
  }

  function applySnapshot(snapshot) {
    state.search = snapshot.search || "";
    state.brand = snapshot.brand || "";
    state.series = snapshot.series || "";
    state.columnFilters = snapshot.columnFilters || {};
    state.rangeFilters = snapshot.rangeFilters || {};
    state.featureFilters = snapshot.featureFilters || {};
    state.sortField = snapshot.sortField || "";
    state.sortDir = snapshot.sortDir || "asc";
    state.sortLevels = Array.isArray(snapshot.sortLevels) ? snapshot.sortLevels : [];
    state.mode = snapshot.mode || state.mode || "center";
    if (Array.isArray(snapshot.visibleColumns)) {
      state.visibleColumns = new Set(snapshot.visibleColumns.filter(function (column) {
        return state.columns.indexOf(column) !== -1;
      }));
    }
    els.globalSearch.value = state.search;
    state.page = 1;
    renderEverything();
  }

  function generateSyncId() {
    if (window.crypto && crypto.getRandomValues) {
      var bytes = new Uint8Array(8);
      crypto.getRandomValues(bytes);
      return Array.from(bytes).map(function (byte) {
        return byte.toString(16).padStart(2, "0");
      }).join("");
    }
    return String(Date.now()) + Math.random().toString(16).slice(2);
  }

  function cacheHistories() {
    localStorage.setItem(STORAGE_HISTORY_KEY, JSON.stringify(state.histories));
  }

  function loadCachedHistories() {
    try {
      state.histories = JSON.parse(localStorage.getItem(STORAGE_HISTORY_KEY) || "[]");
    } catch (error) {
      state.histories = [];
    }
  }

  function githubHistoryConfigured() {
    return HISTORY_PROVIDER === "github" &&
      GITHUB_HISTORY &&
      GITHUB_HISTORY.owner &&
      GITHUB_HISTORY.repo &&
      GITHUB_HISTORY.path;
  }

  function githubHistoryApiUrl() {
    return "https://api.github.com/repos/" +
      encodeURIComponent(GITHUB_HISTORY.owner) + "/" +
      encodeURIComponent(GITHUB_HISTORY.repo) + "/contents/" +
      GITHUB_HISTORY.path.split("/").map(encodeURIComponent).join("/");
  }

  function githubHeaders() {
    return {
      Accept: "application/vnd.github+json",
      Authorization: "Bearer " + state.githubToken,
      "X-GitHub-Api-Version": "2022-11-28"
    };
  }

  function decodeBase64Json(content) {
    var clean = String(content || "").replace(/\s/g, "");
    var binary = atob(clean);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return JSON.parse(new TextDecoder("utf-8").decode(bytes));
  }

  function encodeBase64Json(data) {
    var json = JSON.stringify(data, null, 2);
    var bytes = new TextEncoder().encode(json);
    var chunk = "";
    var parts = [];
    bytes.forEach(function (byte, index) {
      chunk += String.fromCharCode(byte);
      if (chunk.length >= 8192 || index === bytes.length - 1) {
        parts.push(chunk);
        chunk = "";
      }
    });
    return btoa(parts.join(""));
  }

  function normalizeHistoryStore(store) {
    var next = store && typeof store === "object" ? store : {};
    if (!next.version) {
      next.version = 1;
    }
    if (!next.profiles || typeof next.profiles !== "object") {
      next.profiles = {};
    }
    return next;
  }

  function readGithubHistoryStore() {
    var url = githubHistoryApiUrl() + "?ref=" + encodeURIComponent(GITHUB_HISTORY.branch || "main");
    return fetch(url, {
      cache: "no-store",
      headers: githubHeaders()
    }).then(function (response) {
      if (response.status === 404) {
        return { sha: null, store: normalizeHistoryStore(null) };
      }
      if (!response.ok) {
        throw new Error("GitHub HTTP " + response.status);
      }
      return response.json();
    }).then(function (data) {
      if (data.store) {
        return data;
      }
      return {
        sha: data.sha,
        store: normalizeHistoryStore(decodeBase64Json(data.content))
      };
    });
  }

  function loadGithubHistory() {
    if (!state.githubToken) {
      els.historyStatus.textContent = "GitHub 私有历史仓库已配置，保存 Token 后可跨设备同步";
      renderHistory();
      return Promise.resolve();
    }
    els.historyStatus.textContent = "正在从 GitHub 私有仓库同步...";
    return readGithubHistoryStore().then(function (result) {
      state.histories = Array.isArray(result.store.profiles[state.syncId]) ?
        result.store.profiles[state.syncId] : [];
      cacheHistories();
      els.historyStatus.textContent = "已从 GitHub 同步 " + state.histories.length + " 条历史";
    }).catch(function () {
      els.historyStatus.textContent = "GitHub 同步失败，已使用本机缓存";
    }).then(renderHistory);
  }

  function saveGithubHistory(histories, retries) {
    return readGithubHistoryStore().then(function (result) {
      var store = normalizeHistoryStore(result.store);
      store.profiles[state.syncId] = histories.slice(-50);
      store.updatedAt = new Date().toISOString();
      var body = {
        message: "Update phone filter history",
        content: encodeBase64Json(store),
        branch: GITHUB_HISTORY.branch || "main"
      };
      if (result.sha) {
        body.sha = result.sha;
      }
      return fetch(githubHistoryApiUrl(), {
        method: "PUT",
        headers: Object.assign({ "Content-Type": "application/json" }, githubHeaders()),
        body: JSON.stringify(body)
      }).then(function (response) {
        if (response.status === 409 && retries > 0) {
          return saveGithubHistory(histories, retries - 1);
        }
        if (!response.ok) {
          throw new Error("GitHub HTTP " + response.status);
        }
      });
    });
  }

  function loadWorkerHistory() {
    if (!state.syncId) {
      return Promise.resolve();
    }
    els.historyStatus.textContent = "正在同步历史...";
    return fetchJson(HISTORY_API + "?syncId=" + encodeURIComponent(state.syncId))
      .then(function (data) {
        state.histories = Array.isArray(data.histories) ? data.histories : [];
        cacheHistories();
        els.historyStatus.textContent = "已同步 " + state.histories.length + " 条历史";
      })
      .catch(function () {
        els.historyStatus.textContent = "服务端历史暂不可用，已使用本机缓存";
      })
      .then(renderHistory);
  }

  function loadRemoteHistory() {
    if (!state.syncId) {
      return Promise.resolve();
    }
    if (githubHistoryConfigured()) {
      return loadGithubHistory();
    }
    return loadWorkerHistory();
  }

  function saveRemoteHistory() {
    var rows = getFilteredRows();
    var snapshot = snapshotFilters();
    var activeNames = [];
    (state.config.conditions || []).forEach(function (condition) {
      if (state.featureFilters[condition.id] || state.rangeFilters[condition.id]) {
        activeNames.push(condition.label);
      }
    });
    var name = activeNames.length ? activeNames.join(" + ") : (state.search || state.brand || state.series || "自定义筛选");
    var item = {
      id: String(Date.now()),
      name: name,
      state: snapshot,
      resultCount: rows.length,
      createdAt: new Date().toISOString()
    };

    state.histories.push(item);
    state.histories = state.histories.slice(-50);
    cacheHistories();
    renderHistory();
    els.historyStatus.textContent = "正在保存...";

    if (githubHistoryConfigured()) {
      if (!state.githubToken) {
        els.historyStatus.textContent = "已保存在本机；保存 GitHub Token 后可跨设备同步";
        return Promise.resolve();
      }
      return saveGithubHistory(state.histories, 1).then(function () {
        els.historyStatus.textContent = "已保存到 GitHub 私有仓库";
      }).catch(function () {
        els.historyStatus.textContent = "GitHub 保存失败，已保存在本机";
      });
    }

    return fetch(HISTORY_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ syncId: state.syncId, history: item })
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      els.historyStatus.textContent = "已保存到服务端";
    }).catch(function () {
      els.historyStatus.textContent = "服务端保存失败，已保存在本机";
    });
  }

  function bindEvents() {

    els.centerMode.addEventListener("click", function () { state.mode = "center"; renderEverything(); });
    els.tableMode.addEventListener("click", function () {
      state.mode = "table";
      state.expandedSeries.clear();
      renderEverything();
    });
    if (els.centerBrandFilter && els.centerSeriesFilter) {
      els.centerBrandFilter.addEventListener("change", function (event) { state.brand = event.target.value; state.series = ""; state.page = 1; state.cardLimit = 24; renderEverything(); });
      els.centerSeriesFilter.addEventListener("change", function (event) { state.series = event.target.value; state.page = 1; state.cardLimit = 24; renderResultsOnly(); renderCenterFilters(); });
    }
    els.centerConditionList.addEventListener("change", function (event) {
      if (event.target.type !== "checkbox") { return; }
      var condition = (state.config.conditions || []).find(function (item) { return item.id === event.target.dataset.conditionId; });
      if (!condition) { return; }
      if (condition.type === "range") {
        if (event.target.checked) { state.rangeFilters[condition.id] = { min: condition.min || "", max: condition.max || "" }; }
        else { delete state.rangeFilters[condition.id]; }
      } else {
        state.featureFilters[condition.id] = event.target.checked;
        if (!event.target.checked) { delete state.featureFilters[condition.id]; }
      }
      state.page = 1; state.cardLimit = 24; renderConditions(); renderCenterFilters(); renderResultsOnly();
    });
    els.cardList.addEventListener("click", function (event) {
      var toggle = event.target.closest(".series-card-toggle");
      if (!toggle) { return; }
      var key = toggle.dataset.seriesKey;
      if (state.expandedSeries.has(key)) {
        state.expandedSeries.delete(key);
      } else {
        state.expandedSeries.add(key);
      }
      renderResultsOnly();
    });
    els.loadMoreCards.addEventListener("click", function () { state.cardLimit += 24; renderResultsOnly(); });
    els.addSortLevel.addEventListener("click", function () { state.sortLevels.push({ field: state.columns[0] || "", dir: "asc", customOrder: "" }); state.sortField = ""; renderCustomSortPanel(); renderResultsOnly(); });
    els.clearSortLevels.addEventListener("click", function () { state.sortLevels = []; state.sortField = ""; state.sortDir = "asc"; renderCustomSortPanel(); renderTableHead(); renderResultsOnly(); });
    els.customSortLevels.addEventListener("change", function (event) {
      var row = event.target.closest(".sort-level"); if (!row) { return; }
      var level = state.sortLevels[Number(row.dataset.index)]; if (!level) { return; }
      level[event.target.dataset.role] = event.target.value; state.sortField = ""; renderResultsOnly();
    });
    els.customSortLevels.addEventListener("input", function (event) {
      if (event.target.dataset.role !== "customOrder") { return; }
      var row = event.target.closest(".sort-level"); var level = state.sortLevels[Number(row.dataset.index)]; if (!level) { return; }
      level.customOrder = event.target.value; state.sortField = ""; renderResultsOnly();
    });
    els.customSortLevels.addEventListener("click", function (event) {
      var role = event.target.dataset.role; if (["remove", "up", "down"].indexOf(role) === -1) { return; }
      var row = event.target.closest(".sort-level"); var index = Number(row.dataset.index);
      if (role === "remove") { state.sortLevels.splice(index, 1); }
      if (role === "up" && index > 0) { var prev = state.sortLevels[index - 1]; state.sortLevels[index - 1] = state.sortLevels[index]; state.sortLevels[index] = prev; }
      if (role === "down" && index < state.sortLevels.length - 1) { var next = state.sortLevels[index + 1]; state.sortLevels[index + 1] = state.sortLevels[index]; state.sortLevels[index] = next; }
      renderCustomSortPanel(); renderResultsOnly();
    });

    els.globalSearch.addEventListener("compositionstart", function () { state.composing = true; });
    els.globalSearch.addEventListener("compositionend", function (event) {
      state.composing = false;
      state.search = event.target.value;
      state.page = 1;
      renderResultsOnly();
    });
    els.globalSearch.addEventListener("input", function (event) {
      if (state.composing) {
        return;
      }
      state.search = event.target.value;
      state.page = 1;
      renderResultsOnly();
    });

    if (els.brandFilter && els.seriesFilter) {
      els.brandFilter.addEventListener("change", function (event) {
        state.brand = event.target.value;
        state.series = "";
        state.page = 1;
        renderEverything();
      });

      els.seriesFilter.addEventListener("change", function (event) {
        state.series = event.target.value;
        state.page = 1;
        renderResultsOnly();
      });
    }

    els.pageSize.addEventListener("change", function (event) {
      state.pageSize = Number(event.target.value);
      state.page = 1;
      renderResultsOnly();
    });

    els.tableHead.addEventListener("click", function (event) {
      var button = event.target.closest(".sort-button");
      if (!button) {
        return;
      }
      var column = button.dataset.column;
      state.sortLevels = [];
      if (state.sortField === column) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortField = column;
        state.sortDir = "asc";
      }
      renderTableHead();
      renderResultsOnly();
    });

    els.tableHead.addEventListener("compositionstart", function () { state.composing = true; });
    els.tableHead.addEventListener("compositionend", function (event) {
      if (!event.target.classList.contains("filter-input")) {
        return;
      }
      state.composing = false;
      state.columnFilters[event.target.dataset.column] = { operator: "contains", value: event.target.value };
      state.page = 1;
      renderResultsOnly();
    });
    els.tableHead.addEventListener("input", function (event) {
      if (!event.target.classList.contains("filter-input") || state.composing) {
        return;
      }
      state.columnFilters[event.target.dataset.column] = { operator: "contains", value: event.target.value };
      state.page = 1;
      renderResultsOnly();
    });

    els.conditionList.addEventListener("change", function (event) {
      if (event.target.type !== "checkbox") {
        return;
      }
      state.featureFilters[event.target.dataset.conditionId] = event.target.checked;
      if (!event.target.checked) {
        delete state.featureFilters[event.target.dataset.conditionId];
      }
      state.page = 1;
      renderCenterFilters();
      renderSelectedTags();
      renderResultsOnly();
    });

    els.conditionList.addEventListener("click", function (event) {
      if (event.target.tagName !== "BUTTON") {
        return;
      }
      var id = event.target.dataset.conditionId;
      var inputs = els.conditionList.querySelectorAll('input[data-condition-id="' + id + '"][data-side]');
      var value = {};
      inputs.forEach(function (input) {
        value[input.dataset.side] = input.value;
      });
      state.rangeFilters[id] = value;
      state.page = 1;
      renderCenterFilters();
      renderSelectedTags();
      renderResultsOnly();
    });

    els.applyFieldFilter.addEventListener("click", function () {
      if (!els.fieldSelect.value || !els.fieldValue.value) {
        return;
      }
      state.columnFilters[els.fieldSelect.value] = {
        operator: els.fieldOperator.value,
        value: els.fieldValue.value
      };
      els.fieldValue.value = "";
      state.page = 1;
      renderTableHead();
      renderResultsOnly();
    });

    els.activeFilters.addEventListener("click", function (event) {
      if (event.target.tagName !== "BUTTON") {
        return;
      }
      delete state.columnFilters[event.target.dataset.column];
      state.page = 1;
      renderTableHead();
      renderResultsOnly();
    });

    els.columnList.addEventListener("change", function (event) {
      if (event.target.tagName !== "INPUT") {
        return;
      }
      if (event.target.checked) {
        state.visibleColumns.add(event.target.dataset.column);
      } else {
        state.visibleColumns.delete(event.target.dataset.column);
      }
      renderTableHead();
      renderResultsOnly();
    });

    els.columnSearch.addEventListener("input", function (event) {
      state.columnSearch = event.target.value;
      renderColumnList();
    });

    els.showCoreColumns.addEventListener("click", function () {
      state.visibleColumns = new Set();
      (state.config.defaultVisibleColumns || []).forEach(function (column) {
        if (state.columns.indexOf(column) !== -1) {
          state.visibleColumns.add(column);
        }
      });
      renderTableHead();
      renderColumnList();
      renderResultsOnly();
    });

    els.showAllColumns.addEventListener("click", function () {
      state.visibleColumns = new Set(state.columns);
      renderTableHead();
      renderColumnList();
      renderResultsOnly();
    });

    els.resetFilters.addEventListener("click", function () {
      state.columnFilters = {};
      state.rangeFilters = cloneDefaultRangeFilters();
      state.featureFilters = cloneDefaultFeatureFilters();
      state.search = "";
      state.brand = "";
      state.series = "";
      state.sortField = "";
      state.sortDir = "asc";
      state.sortLevels = [];
      state.cardLimit = 24;
      state.page = 1;
      els.globalSearch.value = "";
      renderEverything();
    });

    els.prevPage.addEventListener("click", function () {
      state.page = Math.max(1, state.page - 1);
      renderResultsOnly();
    });

    els.nextPage.addEventListener("click", function () {
      state.page += 1;
      renderResultsOnly();
    });

    function jumpToPage() {
      var pageCount = Math.max(1, Math.ceil(getFilteredRows().length / state.pageSize));
      var rawValue = els.pageJump.value.trim();
      var requested = Number(rawValue);
      if (!rawValue || !Number.isInteger(requested)) {
        els.pageJump.value = String(state.page);
        return;
      }
      state.page = Math.min(pageCount, Math.max(1, requested));
      renderResultsOnly();
    }

    els.goPage.addEventListener("click", jumpToPage);
    els.pageJump.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        jumpToPage();
      }
    });

    els.saveHistory.addEventListener("click", saveRemoteHistory);
    els.copySyncId.addEventListener("click", function () {
      navigator.clipboard.writeText(state.syncId).catch(function () {});
      els.historyStatus.textContent = "同步码已复制";
    });
    els.loadHistory.addEventListener("click", function () {
      state.syncId = els.historySyncId.value.trim();
      localStorage.setItem(STORAGE_SYNC_KEY, state.syncId);
      loadRemoteHistory();
    });
    els.saveGithubToken.addEventListener("click", function () {
      var token = els.githubToken.value.trim();
      if (!token) {
        els.historyStatus.textContent = "Token 留空，继续使用本机已有设置";
        return;
      }
      state.githubToken = token;
      localStorage.setItem(STORAGE_GITHUB_TOKEN_KEY, token);
      els.githubToken.value = "";
      els.githubToken.placeholder = "已保存，留空保持不变";
      loadRemoteHistory();
    });
    els.clearGithubToken.addEventListener("click", function () {
      state.githubToken = "";
      localStorage.removeItem(STORAGE_GITHUB_TOKEN_KEY);
      els.githubToken.value = "";
      els.githubToken.placeholder = "仅保存在本机";
      els.historyStatus.textContent = "GitHub Token 已清除，当前使用本机缓存";
    });
    els.historyList.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-history-id]");
      if (!button) {
        return;
      }
      var item = state.histories.find(function (history) { return history.id === button.dataset.historyId; });
      if (item) {
        applySnapshot(item.state || {});
      }
    });

    els.exportCsv.addEventListener("click", exportCurrentCsv);
    els.exportJson.addEventListener("click", exportCurrentJson);
  }

  function initializeRows(rows) {
    var normalized = (Array.isArray(rows) ? rows : []).map(function (row) {
      if (!row["品牌"] && row["brand"]) {
        row["品牌"] = row["brand"];
      }
      return row;
    });
    state.rows = normalized;
    state.expandedSeries.clear();
    state.seriesViewSignature = "";
    state.cardLimit = 24;
    state.rangeFilters = cloneDefaultRangeFilters();
    state.featureFilters = cloneDefaultFeatureFilters();
    state.columns = buildColumns(state.rows);
    state.visibleColumns = new Set();
    (state.config.defaultVisibleColumns || []).forEach(function (column) {
      if (state.columns.indexOf(column) !== -1) {
        state.visibleColumns.add(column);
      }
    });
    if (!state.visibleColumns.size) {
      state.visibleColumns = new Set(state.columns.slice(0, Math.min(18, state.columns.length)));
    }
  }

  function loadData() {
    return Promise.all([
      fetchJson("filter_conditions.json").catch(function () { return fallbackConfig; }),
      fetchJson("data/manifest.json").catch(function () { return null; })
    ]).then(function (results) {
      state.config = Object.assign({}, fallbackConfig, results[0] || {});
      state.manifest = results[1];
      if (!state.manifest) {
        initializeRows(SAMPLE_ROWS);
        els.dataMeta.textContent = "本地预览示例 · GitHub Pages 部署后自动加载最新数据";
        return;
      }
      return fetchJson(state.manifest.files.latestJson || "data/latest.json").then(function (latest) {
        initializeRows(latest);
        var dateText = state.manifest.date ? "数据日期 " + state.manifest.date : "最新数据";
        els.dataMeta.textContent = dateText + " · 综合收录 " + state.rows.length + " 台手机";
      });
    });
  }

  function initSync() {
    state.syncId = localStorage.getItem(STORAGE_SYNC_KEY) || DEFAULT_SYNC_ID || generateSyncId();
    localStorage.setItem(STORAGE_SYNC_KEY, state.syncId);
    state.githubToken = localStorage.getItem(STORAGE_GITHUB_TOKEN_KEY) || "";
    if (state.githubToken) {
      els.githubToken.placeholder = "已保存，留空保持不变";
    }
    loadCachedHistories();
    renderHistory();
    return loadRemoteHistory();
  }

  bindEvents();
  loadData().then(function () {
    renderEverything();
    initSync();
  });
}());
