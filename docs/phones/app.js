(function () {
  "use strict";

  var CORE_COLUMNS = [
    "型号",
    "品牌",
    "上市时间",
    "价格",
    "验证状态",
    "数据来源",
    "处理器",
    "内存",
    "存储",
    "屏幕",
    "屏占比",
    "电池",
    "机身厚度",
    "机身重量",
    "指纹识别",
    "面部识别",
    "网络类型",
    "NFC",
    "连接与共享",
    "机身接口",
    "有线充电",
    "无线充电",
    "快充协议",
    "交叉验证差异",
    "散热",
    "广角",
    "Geekbench6单核",
    "是否可解BL锁",
    "root或越狱",
  ];

  var DEFAULT_HIDDEN_COLUMNS = new Set(["手机ID", "source"]);

  var SAMPLE_ROWS = [
    {
      "数据来源": "中关村在线+太平洋电脑网",
      "验证状态": "双源一致",
      "交叉验证差异": "-",
      "品牌": "示例品牌",
      "型号": "等待 GitHub Pages 发布最新数据",
      "上市时间": "2024",
      "价格": "2999",
      "处理器": "骁龙8 Gen3",
      "内存": "12GB",
      "存储": "256GB",
      "屏幕": "6.7英寸",
      "电池": "5000mAh",
      "屏占比": "93.4%",
      "机身厚度": "7.9mm",
      "机身重量": "199g",
      "指纹识别": "屏幕指纹",
      "面部识别": "支持",
      "网络类型": "5G / 4G / 3G",
      "NFC": "支持",
      "连接与共享": "OTG / WLAN热点",
      "机身接口": "USB Type-C",
      "有线充电": "100W",
      "无线充电": "50W",
      "快充协议": "PD / QC / SuperVOOC",
      "交叉验证差异": "-",
      "散热": "VC液冷",
      "广角": "120°",
      "Geekbench6单核": "2240",
      "是否可解BL锁": "是",
      "root或越狱": "可永久root (Magisk)",
    },
  ];

  var STORAGE_KEYS = {
    history: "phoneFilterHistory.v2",
    gistId: "phoneFilterHistory.gistId",
    gistToken: "phoneFilterHistory.gistToken",
  };

  var HISTORY_FILE = "phone-filter-history.json";
  var HISTORY_GIST_DESCRIPTION = "phones.jiucai.eu.org filter history";

  var OPERATORS = [
    ["contains", "包含"],
    ["not_contains", "不包含"],
    ["equals", "等于"],
    ["has_value", "有值"],
    ["empty", "无值"],
    ["gte", "数值≥"],
    ["lte", "数值≤"],
    ["between", "数值范围"],
  ];

  var state = {
    manifest: null,
    latestRows: [],
    rows: [],
    columns: [],
    visibleColumns: new Set(),
    advancedFilters: [],
    search: "",
    brand: "",
    rootStatus: "",
    blStatus: "",
    sortField: "",
    sortDir: "asc",
    page: 1,
    pageSize: 100,
    columnSearch: "",
    facetField: "",
    history: [],
    composing: false,
    inputTimer: null,
  };

  var els = {
    dataMeta: document.getElementById("dataMeta"),
    globalSearch: document.getElementById("globalSearch"),
    resetFilters: document.getElementById("resetFilters"),
    exportCsv: document.getElementById("exportCsv"),
    exportJson: document.getElementById("exportJson"),
    visibleCount: document.getElementById("visibleCount"),
    totalCount: document.getElementById("totalCount"),
    zolCount: document.getElementById("zolCount"),
    pconlineCount: document.getElementById("pconlineCount"),
    cnmoCount: document.getElementById("cnmoCount"),
    columnCount: document.getElementById("columnCount"),
    verifiedCount: document.getElementById("verifiedCount"),
    brandFilter: document.getElementById("brandFilter"),
    rootFilter: document.getElementById("rootFilter"),
    blFilter: document.getElementById("blFilter"),
    pageSize: document.getElementById("pageSize"),
    tableHead: document.getElementById("tableHead"),
    tableBody: document.getElementById("tableBody"),
    emptyState: document.getElementById("emptyState"),
    prevPage: document.getElementById("prevPage"),
    nextPage: document.getElementById("nextPage"),
    pageInfo: document.getElementById("pageInfo"),
    advancedFilterList: document.getElementById("advancedFilterList"),
    addAdvancedFilter: document.getElementById("addAdvancedFilter"),
    activeFilters: document.getElementById("activeFilters"),
    facetField: document.getElementById("facetField"),
    facetMin: document.getElementById("facetMin"),
    facetMax: document.getElementById("facetMax"),
    applyFacetRange: document.getElementById("applyFacetRange"),
    facetOptions: document.getElementById("facetOptions"),
    historyName: document.getElementById("historyName"),
    saveHistory: document.getElementById("saveHistory"),
    historyList: document.getElementById("historyList"),
    gistToken: document.getElementById("gistToken"),
    connectGist: document.getElementById("connectGist"),
    pullHistory: document.getElementById("pullHistory"),
    pushHistory: document.getElementById("pushHistory"),
    historySyncStatus: document.getElementById("historySyncStatus"),
    showCoreColumns: document.getElementById("showCoreColumns"),
    showAllColumns: document.getElementById("showAllColumns"),
    columnSearch: document.getElementById("columnSearch"),
    columnList: document.getElementById("columnList"),
    downloadList: document.getElementById("downloadList"),
  };

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status + " " + url);
      }
      return response.json();
    });
  }

  function readLocalJson(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function writeLocalJson(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function uniqueValues(rows, field) {
    var values = Array.from(
      new Set(
        rows
          .map(function (row) {
            return String(row[field] || "").trim();
          })
          .filter(Boolean)
      )
    );
    return values.sort(function (a, b) {
      return a.localeCompare(b, "zh-Hans", { numeric: true });
    });
  }

  function buildColumns(rows) {
    var seen = new Set();
    var columns = [];

    CORE_COLUMNS.forEach(function (column) {
      if (rows.some(function (row) { return Object.prototype.hasOwnProperty.call(row, column); })) {
        seen.add(column);
        columns.push(column);
      }
    });

    rows.forEach(function (row) {
      Object.keys(row).forEach(function (column) {
        if (!seen.has(column)) {
          seen.add(column);
          columns.push(column);
        }
      });
    });

    return columns;
  }

  function normalizeText(value) {
    return String(value == null ? "" : value).toLowerCase();
  }

  function numbersIn(value) {
    return String(value == null ? "" : value)
      .match(/\d+(?:\.\d+)?/g)
      ?.map(Number)
      .filter(function (number) { return Number.isFinite(number); }) || [];
  }

  function firstNumber(value) {
    var numbers = numbersIn(value);
    return numbers.length ? numbers[0] : null;
  }

  function hasValue(value) {
    var text = String(value == null ? "" : value).trim();
    return Boolean(text && text !== "-");
  }

  function compactSpecValue(column, value) {
    var text = String(value == null || value === "" ? "-" : value).trim();
    if (!text || text === "-") {
      return "-";
    }

    text = text
      .replace(/>/g, "")
      .replace(/纠错/g, "")
      .replace(/查看更多[^，,；;|]*/g, "")
      .replace(/更多[^，,；;|]*手机/g, "")
      .replace(/手机性能排行/g, "")
      .replace(/•[^•，,；;|]+是什么•查看所有[^，,；;|]*/g, "")
      .replace(/\s+/g, " ")
      .replace(/，\s*，/g, "，")
      .replace(/[,，；;|\s]+$/g, "")
      .trim();

    if (column === "网络类型") {
      return Array.from(new Set(text.match(/(?:[2345]G|Wi-?Fi ?\d(?:\.\d)?|LTE)/ig) || []))
        .join(" / ") || text;
    }
    if (column === "NFC" || column === "NFC功能") {
      return /不支持|无/.test(text) ? "不支持" : (/NFC|支持/.test(text) ? "支持" : text);
    }
    if (column === "指纹识别") {
      text = text.replace(/识别/g, "").replace(/屏幕指纹/g, "屏幕指纹").replace(/侧面指纹/g, "侧边指纹");
      return text || "-";
    }
    if (column === "面部识别") {
      if (/3D|Face ID|结构光/i.test(text)) {
        return "支持 3D";
      }
      if (/2D|Face Wake|人脸|面部|支持/i.test(text)) {
        return "支持";
      }
      return text;
    }
    if (column === "机身接口") {
      return text.replace(/接口/g, "").replace(/USB Type-C/g, "USB-C");
    }
    if (column === "有线充电" || column === "无线充电") {
      var watts = text.match(/\d+(?:\.\d+)?\s*[wW]/g);
      if (watts && watts.length) {
        return Array.from(new Set(watts.map(function (item) { return item.replace(/\s+/g, "").toUpperCase(); }))).join(" / ");
      }
      return text.replace(/^支持[，,]?/, "支持");
    }
    if (column === "快充协议") {
      return Array.from(new Set(text.match(/SuperVOOC|VOOC|PD\d*(?:\.\d)?|QC\d*(?:\.\d)?|PPS|UFCS|FlashCharge|WarpCharge/ig) || []))
        .join(" / ") || text;
    }
    if (column === "交叉验证差异") {
      return text.length > 160 ? text.slice(0, 157) + "..." : text;
    }
    return text.length > 220 ? text.slice(0, 217) + "..." : text;
  }

  function newFilter(field, op, value) {
    return {
      id: "f_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8),
      field: field || state.columns[0] || "",
      op: op || "contains",
      value: value || "",
      min: "",
      max: "",
    };
  }

  function setDataset() {
    state.rows = state.latestRows;
    state.columns = buildColumns(state.rows);
    state.visibleColumns = new Set();
    CORE_COLUMNS.forEach(function (column) {
      if (state.columns.indexOf(column) !== -1 && !DEFAULT_HIDDEN_COLUMNS.has(column)) {
        state.visibleColumns.add(column);
      }
    });
    if (!state.visibleColumns.size) {
      state.visibleColumns = new Set(state.columns.filter(function (column) {
        return !DEFAULT_HIDDEN_COLUMNS.has(column);
      }).slice(0, Math.min(18, state.columns.length)));
    }
    state.advancedFilters = [];
    state.facetField = state.columns.indexOf("品牌") !== -1 ? "品牌" : state.columns[0] || "";
    state.history = readLocalJson(STORAGE_KEYS.history, []);
    els.gistToken.value = localStorage.getItem(STORAGE_KEYS.gistToken) || "";
    renderFilterControls();
    renderAdvancedFilterRows();
    renderHistory();
    renderDataViews();
  }

  function rowMatchesAdvancedFilter(row, filter) {
    var raw = row[filter.field];
    var text = normalizeText(raw);
    var value = normalizeText(filter.value);
    var nums = numbersIn(raw);
    var min = filter.min === "" ? null : Number(filter.min);
    var max = filter.max === "" ? null : Number(filter.max);

    if (!filter.field) {
      return true;
    }
    if (filter.op === "has_value") {
      return hasValue(raw);
    }
    if (filter.op === "empty") {
      return !hasValue(raw);
    }
    if (filter.op === "equals") {
      return text === value;
    }
    if (filter.op === "not_contains") {
      return text.indexOf(value) === -1;
    }
    if (filter.op === "gte") {
      return Number.isFinite(min) && nums.some(function (number) { return number >= min; });
    }
    if (filter.op === "lte") {
      return Number.isFinite(max) && nums.some(function (number) { return number <= max; });
    }
    if (filter.op === "between") {
      return nums.some(function (number) {
        return (min === null || number >= min) && (max === null || number <= max);
      });
    }
    return text.indexOf(value) !== -1;
  }

  function getFilteredRows() {
    var rows = state.rows.slice();
    var search = normalizeText(state.search);

    if (state.brand) {
      rows = rows.filter(function (row) { return row["品牌"] === state.brand; });
    }
    if (state.rootStatus) {
      rows = rows.filter(function (row) { return (row["root或越狱"] || "").indexOf(state.rootStatus) !== -1; });
    }
    if (state.blStatus) {
      rows = rows.filter(function (row) { return row["是否可解BL锁"] === state.blStatus; });
    }
    if (search) {
      rows = rows.filter(function (row) {
        return Object.keys(row).some(function (key) {
          return normalizeText(row[key]).indexOf(search) !== -1 || normalizeText(key).indexOf(search) !== -1;
        });
      });
    }

    state.advancedFilters.forEach(function (filter) {
      rows = rows.filter(function (row) {
        return rowMatchesAdvancedFilter(row, filter);
      });
    });

    if (state.sortField) {
      rows.sort(function (a, b) {
        var av = a[state.sortField];
        var bv = b[state.sortField];
        var an = firstNumber(av);
        var bn = firstNumber(bv);
        var result;

        if (an !== null && bn !== null) {
          result = an - bn;
        } else {
          result = String(av || "").localeCompare(String(bv || ""), "zh-Hans", { numeric: true });
        }

        return state.sortDir === "asc" ? result : -result;
      });
    }

    return rows;
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

  function renderFilterControls() {
    renderOptions(els.brandFilter, uniqueValues(state.rows, "品牌"), "品牌");
    els.brandFilter.value = state.brand;
    els.rootFilter.value = state.rootStatus;
    els.blFilter.value = state.blStatus;

    els.facetField.textContent = "";
    state.columns.forEach(function (column) {
      var option = document.createElement("option");
      option.value = column;
      option.textContent = column;
      els.facetField.appendChild(option);
    });
    els.facetField.value = state.facetField;
    renderFacetOptions();
  }

  function sortMark(column) {
    if (state.sortField !== column) {
      return "";
    }
    return state.sortDir === "asc" ? "↑" : "↓";
  }

  function renderTable(rows) {
    var visibleColumns = state.columns.filter(function (column) {
      return state.visibleColumns.has(column);
    });
    var start = (state.page - 1) * state.pageSize;
    var pageRows = rows.slice(start, start + state.pageSize);

    els.tableHead.textContent = "";
    els.tableBody.textContent = "";

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

    els.tableHead.appendChild(titleRow);

    pageRows.forEach(function (row) {
      var tr = document.createElement("tr");
      visibleColumns.forEach(function (column) {
        var td = document.createElement("td");
        td.textContent = compactSpecValue(column, row[column]);
        td.title = row[column] == null || row[column] === "" ? "" : String(row[column]);
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

    state.columns
      .filter(function (column) {
        return !query || normalizeText(column).indexOf(query) !== -1;
      })
      .forEach(function (column) {
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

  function activeFilterText(filter) {
    if (filter.op === "has_value") {
      return filter.field + ": 有值";
    }
    if (filter.op === "empty") {
      return filter.field + ": 无值";
    }
    if (filter.op === "gte") {
      return filter.field + " ≥ " + filter.min;
    }
    if (filter.op === "lte") {
      return filter.field + " ≤ " + filter.max;
    }
    if (filter.op === "between") {
      return filter.field + " " + (filter.min || "-∞") + " 至 " + (filter.max || "+∞");
    }
    var label = OPERATORS.find(function (item) { return item[0] === filter.op; });
    return filter.field + " " + (label ? label[1] : "包含") + " " + filter.value;
  }

  function addChip(text, type, value) {
    var chip = document.createElement("span");
    chip.className = "filter-chip";
    chip.textContent = text;
    var close = document.createElement("button");
    close.type = "button";
    close.dataset.type = type;
    close.dataset.value = value || "";
    close.textContent = "×";
    chip.appendChild(close);
    els.activeFilters.appendChild(chip);
  }

  function renderActiveFilters() {
    els.activeFilters.textContent = "";
    if (state.search) {
      addChip("搜索: " + state.search, "search");
    }
    if (state.brand) {
      addChip("品牌: " + state.brand, "brand");
    }
    if (state.rootStatus) {
      addChip("root或越狱: " + state.rootStatus, "root");
    }
    if (state.blStatus) {
      addChip("BL锁: " + state.blStatus, "bl");
    }
    state.advancedFilters.forEach(function (filter) {
      addChip(activeFilterText(filter), "advanced", filter.id);
    });
  }

  function renderDownloads() {
    var files = state.manifest && state.manifest.files ? state.manifest.files : {};
    var links = [
      ["完整 JSON", files.latestJson],
      ["完整 CSV", files.latestCsv],
    ];

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

  function renderAdvancedFilterRows() {
    els.advancedFilterList.textContent = "";
    state.advancedFilters.forEach(function (filter) {
      var row = document.createElement("div");
      row.className = "advanced-filter-row";
      row.dataset.id = filter.id;

      var field = document.createElement("select");
      field.className = "advanced-field";
      state.columns.forEach(function (column) {
        var option = document.createElement("option");
        option.value = column;
        option.textContent = column;
        field.appendChild(option);
      });
      field.value = filter.field;

      var op = document.createElement("select");
      op.className = "advanced-op";
      OPERATORS.forEach(function (item) {
        var option = document.createElement("option");
        option.value = item[0];
        option.textContent = item[1];
        op.appendChild(option);
      });
      op.value = filter.op;

      var value = document.createElement("input");
      value.className = "advanced-value";
      value.placeholder = "值";
      value.value = filter.value || "";
      value.hidden = ["has_value", "empty", "gte", "lte", "between"].indexOf(filter.op) !== -1;

      var min = document.createElement("input");
      min.className = "advanced-min";
      min.inputMode = "decimal";
      min.placeholder = filter.op === "lte" ? "最大值" : "最小值";
      min.value = filter.min || "";
      min.hidden = ["gte", "between"].indexOf(filter.op) === -1;

      var max = document.createElement("input");
      max.className = "advanced-max";
      max.inputMode = "decimal";
      max.placeholder = filter.op === "gte" ? "最小值" : "最大值";
      max.value = filter.max || "";
      max.hidden = ["lte", "between"].indexOf(filter.op) === -1;

      if (filter.op === "gte") {
        min.value = filter.min || filter.value || "";
      }
      if (filter.op === "lte") {
        max.value = filter.max || filter.value || "";
      }

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "icon-button advanced-remove";
      remove.textContent = "×";
      remove.title = "删除条件";

      row.appendChild(field);
      row.appendChild(op);
      row.appendChild(value);
      row.appendChild(min);
      row.appendChild(max);
      row.appendChild(remove);
      els.advancedFilterList.appendChild(row);
    });
  }

  function renderFacetOptions() {
    var field = state.facetField;
    var values = uniqueValues(state.rows, field).slice(0, 80);
    els.facetOptions.textContent = "";
    values.forEach(function (value) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "facet-option";
      button.dataset.value = value;
      button.textContent = value;
      els.facetOptions.appendChild(button);
    });
  }

  function renderHistory() {
    els.historyList.textContent = "";
    state.history.forEach(function (record) {
      var item = document.createElement("div");
      item.className = "history-item";
      item.dataset.id = record.id;

      var button = document.createElement("button");
      button.type = "button";
      button.className = "history-apply";
      button.textContent = record.name || "未命名筛选";

      var meta = document.createElement("span");
      meta.textContent = new Date(record.updatedAt || record.createdAt || Date.now()).toLocaleString("zh-CN", { hour12: false });

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "history-delete";
      remove.textContent = "×";
      remove.title = "删除历史";

      item.appendChild(button);
      item.appendChild(meta);
      item.appendChild(remove);
      els.historyList.appendChild(item);
    });
  }

  function renderDataViews() {
    var filtered = getFilteredRows();
    var pageCount = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > pageCount) {
      state.page = pageCount;
    }

    els.visibleCount.textContent = String(filtered.length);
    els.totalCount.textContent = String(state.rows.length);
    els.columnCount.textContent = String(state.visibleColumns.size);
    els.verifiedCount.textContent = String(state.rows.filter(function (row) {
      return String(row["验证状态"] || "").indexOf("双源") === 0;
    }).length);
    // 从 manifest 读取各源数量（优先），否则从数据计算
    var sc = state.manifest && state.manifest.sourceCounts;
    if (sc) {
      els.zolCount.textContent = String(sc["中关村在线"] || 0);
      els.pconlineCount.textContent = String(sc["太平洋电脑网"] || 0);
      els.cnmoCount.textContent = String(sc["CNMO"] || 0);
    } else {
      els.zolCount.textContent = "-";
      els.pconlineCount.textContent = "-";
      els.cnmoCount.textContent = "-";
    }
    els.pageInfo.textContent = "第 " + state.page + " / " + pageCount + " 页";
    els.prevPage.disabled = state.page <= 1;
    els.nextPage.disabled = state.page >= pageCount;

    renderTable(filtered);
    renderColumnList();
    renderActiveFilters();
    renderDownloads();
  }

  function scheduleRender() {
    clearTimeout(state.inputTimer);
    state.inputTimer = setTimeout(function () {
      state.page = 1;
      renderDataViews();
    }, 160);
  }

  function csvEscape(value) {
    var text = String(value == null ? "" : value);
    if (/[",\n\r]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
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
    downloadBlob(
      "phone-config-current.json",
      "application/json;charset=utf-8",
      JSON.stringify(getFilteredRows(), null, 2)
    );
  }

  function currentCriteria() {
    return {
      search: state.search,
      brand: state.brand,
      rootStatus: state.rootStatus,
      blStatus: state.blStatus,
      advancedFilters: state.advancedFilters.map(function (filter) { return Object.assign({}, filter); }),
      visibleColumns: Array.from(state.visibleColumns),
      sortField: state.sortField,
      sortDir: state.sortDir,
      pageSize: state.pageSize,
    };
  }

  function applyCriteria(criteria) {
    state.search = criteria.search || "";
    state.brand = criteria.brand || "";
    state.rootStatus = criteria.rootStatus || "";
    state.blStatus = criteria.blStatus || "";
    state.advancedFilters = (criteria.advancedFilters || []).map(function (filter) {
      return Object.assign(newFilter(filter.field, filter.op, filter.value), filter);
    });
    state.visibleColumns = new Set((criteria.visibleColumns || []).filter(function (column) {
      return state.columns.indexOf(column) !== -1;
    }));
    if (!state.visibleColumns.size) {
      state.visibleColumns = new Set(state.columns.filter(function (column) {
        return !DEFAULT_HIDDEN_COLUMNS.has(column);
      }).slice(0, Math.min(18, state.columns.length)));
    }
    state.sortField = criteria.sortField || "";
    state.sortDir = criteria.sortDir || "asc";
    state.pageSize = Number(criteria.pageSize || 100);
    state.page = 1;

    els.globalSearch.value = state.search;
    els.brandFilter.value = state.brand;
    els.rootFilter.value = state.rootStatus;
    els.blFilter.value = state.blStatus;
    els.pageSize.value = String(state.pageSize);
    renderAdvancedFilterRows();
    renderDataViews();
  }

  function saveHistory() {
    var now = new Date().toISOString();
    var record = {
      id: "h_" + Date.now().toString(36),
      name: els.historyName.value.trim() || new Date().toLocaleString("zh-CN", { hour12: false }) + " 筛选",
      createdAt: now,
      updatedAt: now,
      criteria: currentCriteria(),
    };
    state.history = [record].concat(state.history).slice(0, 80);
    writeLocalJson(STORAGE_KEYS.history, state.history);
    els.historyName.value = "";
    renderHistory();
  }

  function setSyncStatus(text) {
    els.historySyncStatus.textContent = text;
  }

  function gistHeaders() {
    var token = els.gistToken.value.trim();
    if (!token) {
      throw new Error("缺少 GitHub Gist Token");
    }
    localStorage.setItem(STORAGE_KEYS.gistToken, token);
    return {
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + token,
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
  }

  function gistPayload() {
    return {
      version: 2,
      updatedAt: new Date().toISOString(),
      history: state.history,
    };
  }

  function requestGist(url, options) {
    return fetch(url, options).then(function (response) {
      if (!response.ok) {
        throw new Error("GitHub API " + response.status);
      }
      return response.json();
    });
  }

  function findOrCreateGist() {
    var saved = localStorage.getItem(STORAGE_KEYS.gistId);
    var headers = gistHeaders();
    if (saved) {
      return Promise.resolve(saved);
    }
    return requestGist("https://api.github.com/gists?per_page=100", { headers: headers })
      .then(function (gists) {
        var found = gists.find(function (gist) {
          return gist.description === HISTORY_GIST_DESCRIPTION && gist.files && gist.files[HISTORY_FILE];
        });
        if (found) {
          localStorage.setItem(STORAGE_KEYS.gistId, found.id);
          return found.id;
        }
        var files = {};
        files[HISTORY_FILE] = {
          content: JSON.stringify(gistPayload(), null, 2),
        };
        return requestGist("https://api.github.com/gists", {
          method: "POST",
          headers: headers,
          body: JSON.stringify({
            description: HISTORY_GIST_DESCRIPTION,
            public: false,
            files: files,
          }),
        }).then(function (gist) {
          localStorage.setItem(STORAGE_KEYS.gistId, gist.id);
          return gist.id;
        });
      });
  }

  function pullHistory() {
    setSyncStatus("正在拉取...");
    return findOrCreateGist()
      .then(function (gistId) {
        return requestGist("https://api.github.com/gists/" + gistId, { headers: gistHeaders() });
      })
      .then(function (gist) {
        var file = gist.files && gist.files[HISTORY_FILE];
        var remote = file && file.content ? JSON.parse(file.content) : { history: [] };
        var merged = {};
        state.history.concat(remote.history || []).forEach(function (record) {
          merged[record.id] = record;
        });
        state.history = Object.keys(merged)
          .map(function (key) { return merged[key]; })
          .sort(function (a, b) {
            return String(b.updatedAt || b.createdAt).localeCompare(String(a.updatedAt || a.createdAt));
          })
          .slice(0, 80);
        writeLocalJson(STORAGE_KEYS.history, state.history);
        renderHistory();
        setSyncStatus("已拉取并合并历史");
      })
      .catch(function (error) {
        setSyncStatus(error.message);
      });
  }

  function pushHistory() {
    setSyncStatus("正在推送...");
    return findOrCreateGist()
      .then(function (gistId) {
        return requestGist("https://api.github.com/gists/" + gistId, {
          method: "PATCH",
          headers: gistHeaders(),
          body: JSON.stringify({
            description: HISTORY_GIST_DESCRIPTION,
            files: {
              [HISTORY_FILE]: {
                content: JSON.stringify(gistPayload(), null, 2),
              },
            },
          }),
        });
      })
      .then(function () {
        setSyncStatus("已推送到私有 Gist");
      })
      .catch(function (error) {
        setSyncStatus(error.message);
      });
  }

  function getAdvancedFilter(id) {
    return state.advancedFilters.find(function (filter) { return filter.id === id; });
  }

  function addEqualityFilter(field, value) {
    var existing = state.advancedFilters.find(function (filter) {
      return filter.field === field && filter.op === "equals";
    });
    if (existing) {
      existing.value = value;
    } else {
      state.advancedFilters.push(newFilter(field, "equals", value));
    }
    renderAdvancedFilterRows();
    renderDataViews();
  }

  function bindEvents() {
    ["compositionstart", "compositionend"].forEach(function (eventName) {
      document.addEventListener(eventName, function (event) {
        if (!event.target.matches("input")) {
          return;
        }
        state.composing = eventName === "compositionstart";
        if (!state.composing) {
          scheduleRender();
        }
      });
    });

    els.globalSearch.addEventListener("input", function (event) {
      state.search = event.target.value;
      if (!state.composing) {
        scheduleRender();
      }
    });

    els.brandFilter.addEventListener("change", function (event) {
      state.brand = event.target.value;
      state.page = 1;
      renderDataViews();
    });

    els.rootFilter.addEventListener("change", function (event) {
      state.rootStatus = event.target.value;
      state.page = 1;
      renderDataViews();
    });

    els.blFilter.addEventListener("change", function (event) {
      state.blStatus = event.target.value;
      state.page = 1;
      renderDataViews();
    });

    els.pageSize.addEventListener("change", function (event) {
      state.pageSize = Number(event.target.value);
      state.page = 1;
      renderDataViews();
    });

    els.tableHead.addEventListener("click", function (event) {
      var button = event.target.closest(".sort-button");
      if (!button) {
        return;
      }
      var column = button.dataset.column;
      if (state.sortField === column) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortField = column;
        state.sortDir = "asc";
      }
      renderDataViews();
    });

    els.addAdvancedFilter.addEventListener("click", function () {
      state.advancedFilters.push(newFilter());
      renderAdvancedFilterRows();
      renderDataViews();
    });

    els.advancedFilterList.addEventListener("change", function (event) {
      var row = event.target.closest(".advanced-filter-row");
      var filter = row ? getAdvancedFilter(row.dataset.id) : null;
      if (!filter) {
        return;
      }
      if (event.target.classList.contains("advanced-field")) {
        filter.field = event.target.value;
      }
      if (event.target.classList.contains("advanced-op")) {
        filter.op = event.target.value;
      }
      renderAdvancedFilterRows();
      renderDataViews();
    });

    els.advancedFilterList.addEventListener("input", function (event) {
      var row = event.target.closest(".advanced-filter-row");
      var filter = row ? getAdvancedFilter(row.dataset.id) : null;
      if (!filter) {
        return;
      }
      if (event.target.classList.contains("advanced-value")) {
        filter.value = event.target.value;
      }
      if (event.target.classList.contains("advanced-min")) {
        filter.min = event.target.value;
      }
      if (event.target.classList.contains("advanced-max")) {
        filter.max = event.target.value;
      }
      if (!state.composing) {
        scheduleRender();
      }
    });

    els.advancedFilterList.addEventListener("click", function (event) {
      if (!event.target.classList.contains("advanced-remove")) {
        return;
      }
      var row = event.target.closest(".advanced-filter-row");
      state.advancedFilters = state.advancedFilters.filter(function (filter) {
        return filter.id !== row.dataset.id;
      });
      renderAdvancedFilterRows();
      renderDataViews();
    });

    els.activeFilters.addEventListener("click", function (event) {
      if (event.target.tagName !== "BUTTON") {
        return;
      }
      if (event.target.dataset.type === "search") {
        state.search = "";
        els.globalSearch.value = "";
      }
      if (event.target.dataset.type === "brand") {
        state.brand = "";
        els.brandFilter.value = "";
      }
      if (event.target.dataset.type === "root") {
        state.rootStatus = "";
        els.rootFilter.value = "";
      }
      if (event.target.dataset.type === "bl") {
        state.blStatus = "";
        els.blFilter.value = "";
      }
      if (event.target.dataset.type === "advanced") {
        state.advancedFilters = state.advancedFilters.filter(function (filter) {
          return filter.id !== event.target.dataset.value;
        });
        renderAdvancedFilterRows();
      }
      state.page = 1;
      renderDataViews();
    });

    els.facetField.addEventListener("change", function (event) {
      state.facetField = event.target.value;
      els.facetMin.value = "";
      els.facetMax.value = "";
      renderFacetOptions();
    });

    els.facetOptions.addEventListener("click", function (event) {
      if (!event.target.classList.contains("facet-option")) {
        return;
      }
      addEqualityFilter(state.facetField, event.target.dataset.value);
    });

    els.applyFacetRange.addEventListener("click", function () {
      var filter = newFilter(state.facetField, "between");
      filter.min = els.facetMin.value.trim();
      filter.max = els.facetMax.value.trim();
      state.advancedFilters.push(filter);
      renderAdvancedFilterRows();
      renderDataViews();
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
      renderDataViews();
    });

    els.columnSearch.addEventListener("input", function (event) {
      state.columnSearch = event.target.value;
      renderColumnList();
    });

    els.showCoreColumns.addEventListener("click", function () {
      state.visibleColumns = new Set();
      CORE_COLUMNS.forEach(function (column) {
        if (state.columns.indexOf(column) !== -1 && !DEFAULT_HIDDEN_COLUMNS.has(column)) {
          state.visibleColumns.add(column);
        }
      });
      renderDataViews();
    });

    els.showAllColumns.addEventListener("click", function () {
      state.visibleColumns = new Set(state.columns);
      renderDataViews();
    });

    els.resetFilters.addEventListener("click", function () {
      state.advancedFilters = [];
      state.search = "";
      state.brand = "";
      state.rootStatus = "";
      state.blStatus = "";
      state.sortField = "";
      state.sortDir = "asc";
      state.page = 1;
      els.globalSearch.value = "";
      renderAdvancedFilterRows();
      renderDataViews();
    });

    els.prevPage.addEventListener("click", function () {
      state.page = Math.max(1, state.page - 1);
      renderDataViews();
    });

    els.nextPage.addEventListener("click", function () {
      state.page += 1;
      renderDataViews();
    });

    els.saveHistory.addEventListener("click", saveHistory);
    els.connectGist.addEventListener("click", function () {
      setSyncStatus("正在连接...");
      findOrCreateGist()
        .then(function () {
          setSyncStatus("已连接私有 Gist");
        })
        .catch(function (error) {
          setSyncStatus(error.message);
        });
    });
    els.pullHistory.addEventListener("click", pullHistory);
    els.pushHistory.addEventListener("click", pushHistory);

    els.historyList.addEventListener("click", function (event) {
      var item = event.target.closest(".history-item");
      if (!item) {
        return;
      }
      var record = state.history.find(function (entry) { return entry.id === item.dataset.id; });
      if (!record) {
        return;
      }
      if (event.target.classList.contains("history-delete")) {
        state.history = state.history.filter(function (entry) { return entry.id !== record.id; });
        writeLocalJson(STORAGE_KEYS.history, state.history);
        renderHistory();
        return;
      }
      if (event.target.classList.contains("history-apply")) {
        applyCriteria(record.criteria || {});
      }
    });

    els.exportCsv.addEventListener("click", exportCurrentCsv);
    els.exportJson.addEventListener("click", exportCurrentJson);
  }

  function loadData() {
    return fetchJson("data/manifest.json")
      .then(function (manifest) {
        state.manifest = manifest;
        return fetchJson(manifest.files.latestJson || "data/latest.json");
      })
      .then(function (data) {
        state.latestRows = Array.isArray(data) ? data : [];
        var dateText = state.manifest && state.manifest.date ? "数据日期 " + state.manifest.date : "最新数据";
        els.dataMeta.textContent = dateText + " · 共 " + state.latestRows.length + " 条记录";
      })
      .catch(function () {
        state.manifest = null;
        state.latestRows = SAMPLE_ROWS;
        els.dataMeta.textContent = "本地预览示例 · GitHub Pages 部署后自动加载最新 Release 数据";
      });
  }

  bindEvents();
  loadData().then(function () {
    setDataset();
  });
})();
