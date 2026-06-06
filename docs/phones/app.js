(function () {
  "use strict";

  var CORE_COLUMNS = [
    "型号",
    "品牌",
    "上市时间",
    "价格",
    "数据来源",
    "处理器",
    "内存",
    "存储",
    "屏幕",
    "电池",
    "是否可解BL锁",
    "是否可root",
    "root方案",
    "风险等级",
  ];

  var SAMPLE_ROWS = [
    {
      "数据来源": "示例",
      "品牌": "示例品牌",
      "型号": "等待 GitHub Pages 发布最新数据",
      "上市时间": "2024",
      "价格": "2999",
      "处理器": "骁龙8 Gen3",
      "内存": "12GB",
      "存储": "256GB",
      "屏幕": "6.7英寸",
      "电池": "5000mAh",
      "是否可解BL锁": "是",
      "是否可root": "是",
      "root方案": "Magisk",
      "风险等级": "低",
    },
  ];

  var state = {
    manifest: null,
    latestRows: [],
    rows: [],
    columns: [],
    visibleColumns: new Set(),
    columnFilters: {},
    search: "",
    source: "",
    brand: "",
    rootStatus: "",
    blStatus: "",
    sortField: "",
    sortDir: "asc",
    page: 1,
    pageSize: 100,
    columnSearch: "",
  };

  var els = {
    dataMeta: document.getElementById("dataMeta"),
    globalSearch: document.getElementById("globalSearch"),
    resetFilters: document.getElementById("resetFilters"),
    exportCsv: document.getElementById("exportCsv"),
    exportJson: document.getElementById("exportJson"),
    visibleCount: document.getElementById("visibleCount"),
    totalCount: document.getElementById("totalCount"),
    columnCount: document.getElementById("columnCount"),
    sourceCount: document.getElementById("sourceCount"),
    sourceFilter: document.getElementById("sourceFilter"),
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
    fieldSelect: document.getElementById("fieldSelect"),
    fieldValue: document.getElementById("fieldValue"),
    applyFieldFilter: document.getElementById("applyFieldFilter"),
    activeFilters: document.getElementById("activeFilters"),
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

  function setDataset() {
    state.rows = state.latestRows;
    state.columns = buildColumns(state.rows);
    state.visibleColumns = new Set(state.columns.slice(0, Math.min(18, state.columns.length)));
    CORE_COLUMNS.forEach(function (column) {
      if (state.columns.indexOf(column) !== -1) {
        state.visibleColumns.add(column);
      }
    });
    state.columnFilters = {};
    state.page = 1;
    renderEverything();
  }

  function normalizeText(value) {
    return String(value == null ? "" : value).toLowerCase();
  }

  function firstNumber(value) {
    var match = String(value == null ? "" : value).match(/\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function getFilteredRows() {
    var rows = state.rows.slice();
    var search = normalizeText(state.search);

    if (state.source) {
      rows = rows.filter(function (row) { return row["数据来源"] === state.source; });
    }
    if (state.brand) {
      rows = rows.filter(function (row) { return row["品牌"] === state.brand; });
    }
    if (state.rootStatus) {
      rows = rows.filter(function (row) { return row["是否可root"] === state.rootStatus; });
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

    Object.keys(state.columnFilters).forEach(function (column) {
      var value = normalizeText(state.columnFilters[column]);
      if (!value) {
        return;
      }
      rows = rows.filter(function (row) {
        return normalizeText(row[column]).indexOf(value) !== -1;
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

  function renderFilters() {
    renderOptions(els.sourceFilter, uniqueValues(state.rows, "数据来源"), "来源");
    renderOptions(els.brandFilter, uniqueValues(state.rows, "品牌"), "品牌");

    els.sourceFilter.value = state.source;
    els.brandFilter.value = state.brand;
    els.rootFilter.value = state.rootStatus;
    els.blFilter.value = state.blStatus;

    els.fieldSelect.textContent = "";
    state.columns.forEach(function (column) {
      var option = document.createElement("option");
      option.value = column;
      option.textContent = column;
      els.fieldSelect.appendChild(option);
    });
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

    var filterRow = document.createElement("tr");
    filterRow.className = "filter-row";
    visibleColumns.forEach(function (column) {
      var th = document.createElement("th");
      var input = document.createElement("input");
      input.className = "filter-input";
      input.dataset.column = column;
      input.value = state.columnFilters[column] || "";
      input.placeholder = "筛选";
      th.appendChild(input);
      filterRow.appendChild(th);
    });

    els.tableHead.appendChild(titleRow);
    els.tableHead.appendChild(filterRow);

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

  function renderActiveFilters() {
    els.activeFilters.textContent = "";
    Object.keys(state.columnFilters).forEach(function (column) {
      if (!state.columnFilters[column]) {
        return;
      }
      var chip = document.createElement("span");
      chip.className = "filter-chip";
      chip.textContent = column + ": " + state.columnFilters[column];
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

  function renderEverything() {
    var filtered = getFilteredRows();
    var pageCount = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > pageCount) {
      state.page = pageCount;
    }

    els.visibleCount.textContent = String(filtered.length);
    els.totalCount.textContent = String(state.rows.length);
    els.columnCount.textContent = String(state.visibleColumns.size);
    els.sourceCount.textContent = String(uniqueValues(state.rows, "数据来源").length);
    els.pageInfo.textContent = "第 " + state.page + " / " + pageCount + " 页";
    els.prevPage.disabled = state.page <= 1;
    els.nextPage.disabled = state.page >= pageCount;

    renderFilters();
    renderTable(filtered);
    renderColumnList();
    renderActiveFilters();
    renderDownloads();
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

  function bindEvents() {
    els.globalSearch.addEventListener("input", function (event) {
      state.search = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.sourceFilter.addEventListener("change", function (event) {
      state.source = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.brandFilter.addEventListener("change", function (event) {
      state.brand = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.rootFilter.addEventListener("change", function (event) {
      state.rootStatus = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.blFilter.addEventListener("change", function (event) {
      state.blStatus = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.pageSize.addEventListener("change", function (event) {
      state.pageSize = Number(event.target.value);
      state.page = 1;
      renderEverything();
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
      renderEverything();
    });

    els.tableHead.addEventListener("input", function (event) {
      if (!event.target.classList.contains("filter-input")) {
        return;
      }
      state.columnFilters[event.target.dataset.column] = event.target.value;
      state.page = 1;
      renderEverything();
    });

    els.applyFieldFilter.addEventListener("click", function () {
      if (!els.fieldSelect.value) {
        return;
      }
      state.columnFilters[els.fieldSelect.value] = els.fieldValue.value;
      els.fieldValue.value = "";
      state.page = 1;
      renderEverything();
    });

    els.activeFilters.addEventListener("click", function (event) {
      if (event.target.tagName !== "BUTTON") {
        return;
      }
      delete state.columnFilters[event.target.dataset.column];
      state.page = 1;
      renderEverything();
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
      renderEverything();
    });

    els.columnSearch.addEventListener("input", function (event) {
      state.columnSearch = event.target.value;
      renderColumnList();
    });

    els.showCoreColumns.addEventListener("click", function () {
      state.visibleColumns = new Set();
      CORE_COLUMNS.forEach(function (column) {
        if (state.columns.indexOf(column) !== -1) {
          state.visibleColumns.add(column);
        }
      });
      renderEverything();
    });

    els.showAllColumns.addEventListener("click", function () {
      state.visibleColumns = new Set(state.columns);
      renderEverything();
    });

    els.resetFilters.addEventListener("click", function () {
      state.columnFilters = {};
      state.search = "";
      state.source = "";
      state.brand = "";
      state.rootStatus = "";
      state.blStatus = "";
      state.sortField = "";
      state.sortDir = "asc";
      state.page = 1;
      els.globalSearch.value = "";
      renderEverything();
    });

    els.prevPage.addEventListener("click", function () {
      state.page = Math.max(1, state.page - 1);
      renderEverything();
    });

    els.nextPage.addEventListener("click", function () {
      state.page += 1;
      renderEverything();
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
