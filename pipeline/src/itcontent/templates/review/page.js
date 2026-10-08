/* Review page script (docs/04 § Content review loop › Review pages). No network, no dependencies.
 * State (the teacher's verdicts and comments) is saved in localStorage as they type; "Download my review" writes the
 * review file (schemas/review-file.schema.json); "Sign off" adds the signoff block with the hash of every file. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("review-data").textContent);
  var KEY = "italiano-review:" + DATA.scope + ":" + DATA.pageId;
  var META = {};
  DATA.elements.forEach(function (m) { META[m.key] = m; });
  var state = { v: 1, reviewer: "", comments: {}, sent: [], signoff: null };
  var dirty = false;
  var storageWorks = true;

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function nowISO() { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
  function uuid() {
    var b = new Uint8Array(16);
    window.crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    var h = Array.prototype.map.call(b, function (x) { return (x + 0x100).toString(16).slice(1); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  // ------------------------------------------------------------ storage

  function load() {
    try {
      var raw = window.localStorage.getItem(KEY);
      if (raw) {
        var saved = JSON.parse(raw);
        if (saved && saved.v === 1) {
          state.reviewer = saved.reviewer || "";
          state.comments = saved.comments || {};
          state.sent = saved.sent || [];
          state.signoff = saved.signoff || null;
          dirty = !!saved.dirty;
        }
      }
      var probe = KEY + ":probe";
      window.localStorage.setItem(probe, "1");
      window.localStorage.removeItem(probe);
    } catch (e) {
      storageWorks = false;
    }
  }
  function persist() {
    try {
      var copy = { v: 1, reviewer: state.reviewer, comments: state.comments, sent: state.sent, signoff: state.signoff, dirty: dirty };
      window.localStorage.setItem(KEY, JSON.stringify(copy));
      storageWorks = true;
    } catch (e) {
      storageWorks = false;
    }
    updateHeader();
  }
  function changed() {
    dirty = true;
    persist();
  }

  // ------------------------------------------------------------ comments

  function filled(meta, c) {
    return !!c && (meta.adj ? !!c.decision : !!c.verdict);
  }
  function asks(meta, c) {
    // A comment that still asks for something: a change or a question (an adjudication other than "wrong").
    return filled(meta, c) && (meta.adj ? c.decision !== "wrong" : c.verdict !== "ok");
  }
  function hasText(c) {
    return !!c && !!((c.comment || "").trim() || (c.suggestion || "").trim() || (c.hint || "").trim());
  }
  function touch(key, fn) {
    var c = state.comments[key] || {};
    fn(c);
    if (!c.verdict && !c.decision && !hasText(c) && !c.reopens) {
      delete state.comments[key];
    } else {
      if (!c.id || state.sent.indexOf(c.id) >= 0) c.id = uuid(); // edited after a download: a new comment
      c.at = nowISO();
      state.comments[key] = c;
    }
    if (state.signoff) {
      state.signoff = null;
      message("You changed a comment after signing off, so the sign-off was withdrawn. Sign off again when you're done.");
    }
    changed();
    render(key);
  }
  function fileComment(meta, c) {
    var adj = meta.adj;
    var out = {
      id: c.id,
      target: meta.target,
      file: meta.file,
      quote: meta.quote == null ? null : meta.quote,
      verdict: adj ? (c.decision === "wrong" ? "ok" : "change") : c.verdict,
      category: adj ? "answer-key" : (c.category || null),
      comment: (c.comment || "").trim() || null,
      suggestion: adj ? null : ((c.suggestion || "").trim() || null),
      response: adj ? adj.response : null,
      at: c.at
    };
    if (adj) {
      out.adjudication = {
        decision: c.decision,
        hint: c.decision === "near" ? ((c.hint || "").trim() || null) : null,
        outcome: c.decision === "near" && c.almost ? "almost" : null,
        intent: c.decision !== "wrong" && adj.intents ? (c.intent || null) : null,
        count: adj.count
      };
    }
    if (c.reopens) out.reopens = c.reopens;
    return out;
  }
  function reviewFile() {
    var comments = [];
    var elements = {};
    DATA.elements.forEach(function (meta) {
      var c = state.comments[meta.key];
      if (filled(meta, c)) comments.push(fileComment(meta, c));
      if (meta.fp) elements[meta.target] = meta.fp;
    });
    return {
      format: 1, reviewer: state.reviewer, channel: "page", scope: DATA.scope, created: nowISO(),
      files: DATA.files, elements: elements, comments: comments, signoff: state.signoff
    };
  }
  function download() {
    var file = reviewFile();
    var blob = new Blob([JSON.stringify(file, null, 2) + "\n"], { type: "application/json" });
    var a = el("a", { href: URL.createObjectURL(blob), download: "review-" + file.scope + "-" + file.created.slice(0, 10) + ".json" });
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
    file.comments.forEach(function (c) { if (state.sent.indexOf(c.id) < 0) state.sent.push(c.id); });
    dirty = false;
    persist();
    message("Downloaded " + a.download + " with " + file.comments.length + " comment(s). Send it to the project owner.");
  }

  // ------------------------------------------------------------ controls

  var VERDICTS = [["ok", "✓ OK"], ["change", "✎ Change"], ["question", "? Question"]];
  var DECISIONS = [["accept", "Accept"], ["near", "Near-miss"], ["wrong", "Wrong"]];

  function build(box) {
    var key = box.getAttribute("data-key");
    var meta = META[key];
    if (!meta) return;
    var group = el("div", { class: "verdicts", role: "group", "aria-label": (meta.adj ? "Decision for " : "Verdict for ") + meta.target });
    (meta.adj ? DECISIONS : VERDICTS).forEach(function (v) {
      var b = el("button", { type: "button", class: "v v-" + v[0], "data-v": v[0], "aria-pressed": "false" }, v[1]);
      b.addEventListener("click", function () {
        touch(key, function (c) {
          var field = meta.adj ? "decision" : "verdict";
          c[field] = c[field] === v[0] ? null : v[0];
        });
        if (v[0] !== "ok" && v[0] !== "wrong") { var t = $("textarea", box); if (t && !meta.adj) t.focus(); }
      });
      group.appendChild(b);
    });
    if (!meta.adj) {
      var note = el("button", { type: "button", class: "link add-note" }, "Add a comment");
      note.addEventListener("click", function () {
        box.classList.add("open");
        render(key);
        $("textarea", box).focus();
      });
      group.appendChild(note);
    }
    box.appendChild(group);
    var form = el("div", { class: "form", hidden: "" });
    if (meta.adj) {
      var hint = el("label", { class: "near-only" }, "Hint for learners who give this answer");
      hint.appendChild(el("input", { type: "text", name: "hint" }));
      var almost = el("label", { class: "inline near-only" });
      almost.appendChild(el("input", { type: "checkbox", name: "almost" }));
      almost.appendChild(document.createTextNode(" Nearly right (counts as almost)"));
      form.appendChild(hint);
      form.appendChild(almost);
      if (meta.adj.intents) {
        var pick = el("label", { class: "intent-only" }, "Which answer does it belong to?");
        var sel = el("select", { name: "intent" });
        sel.appendChild(el("option", { value: "" }, "Choose…"));
        meta.adj.intents.forEach(function (i) { sel.appendChild(el("option", { value: i }, i)); });
        pick.appendChild(sel);
        form.appendChild(pick);
      }
    } else {
      var cat = el("label", {}, "Category");
      var select = el("select", { name: "category" });
      select.appendChild(el("option", { value: "" }, "Choose…"));
      DATA.categories.forEach(function (c) { select.appendChild(el("option", { value: c[0] }, c[1])); });
      cat.appendChild(select);
      form.appendChild(cat);
    }
    var com = el("label", {}, "Comment");
    com.appendChild(el("textarea", { name: "comment", rows: "3" }));
    form.appendChild(com);
    if (!meta.adj) {
      var sug = el("label", {}, "Suggested Italian (optional)");
      sug.appendChild(el("input", { type: "text", name: "suggestion", lang: "it" }));
      form.appendChild(sug);
    }
    var clear = el("button", { type: "button", class: "clear" }, "Clear");
    clear.addEventListener("click", function () {
      box.classList.remove("open");
      touch(key, function (c) { Object.keys(c).forEach(function (k) { delete c[k]; }); });
    });
    form.appendChild(clear);
    box.appendChild(form);
    $all("input, select, textarea", form).forEach(function (input) {
      var evt = input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input";
      input.addEventListener(evt, function () {
        touch(key, function (c) {
          c[input.name] = input.type === "checkbox" ? input.checked : input.value;
        });
      });
    });
  }

  function render(key) {
    var box = document.querySelector('.el-review[data-key="' + CSS.escape(key) + '"]');
    var meta = META[key];
    if (!box || !meta) return;
    var c = state.comments[key] || {};
    var current = meta.adj ? c.decision : c.verdict;
    $all("button.v", box).forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-v") === current)); });
    var form = $(".form", box);
    var show = meta.adj ? !!c.decision : (current === "change" || current === "question" || hasText(c) || box.classList.contains("open"));
    if (show) form.removeAttribute("hidden"); else form.setAttribute("hidden", "");
    $all("input, select, textarea", form).forEach(function (input) {
      if (document.activeElement === input) return;
      var v = c[input.name];
      if (input.type === "checkbox") input.checked = !!v; else input.value = v || "";
    });
    $all(".near-only", form).forEach(function (n) { n.hidden = c.decision !== "near"; });
    $all(".intent-only", form).forEach(function (n) { n.hidden = c.decision === "wrong"; });
    var article = box.closest(".el");
    article.classList.toggle("has-verdict", filled(meta, c));
    article.classList.toggle("has-text", asks(meta, c) || hasText(c));
    ["ok", "change", "question"].forEach(function (v) { article.classList.toggle("v-" + v, c.verdict === v); });
  }

  // ------------------------------------------------------------ header, messages, sign-off

  function message(text) {
    var m = $("#message");
    m.textContent = text;
    m.hidden = !text;
  }
  function updateHeader() {
    var total = 0, done = 0;
    DATA.elements.forEach(function (m) {
      if (!m.counted) return;
      total += 1;
      if (filled(m, state.comments[m.key])) done += 1;
    });
    $("#progress-count").textContent = String(done);
    $("#progress-total").textContent = String(total);
    var meter = $("#progress-meter");
    meter.max = total || 1;
    meter.value = done;
    $("#storage-warning").hidden = storageWorks;
    $("#saved").textContent = storageWorks ? (dirty ? "Saved in this browser; not downloaded yet" : "Saved in this browser") : "Not saved";
    var status = $("#signoff-status");
    if (state.signoff) {
      status.hidden = false;
      status.textContent = "Signed off by " + state.signoff.name + " at " + state.signoff.at + ". The downloaded review carries the sign-off.";
    } else {
      status.hidden = true;
    }
  }
  function blockers() {
    var out = [];
    var asking = DATA.elements.filter(function (m) { return asks(m, state.comments[m.key]); }).length;
    if (asking) out.push(asking + " of your comments ask for a change or a question. Sign off once they are resolved.");
    if (DATA.open.length) out.push(DATA.open.length + " earlier comment(s) are still open in the project. Sign off once they are resolved.");
    return out;
  }
  function openSignoff() {
    var dlg = $("#signoff-dialog");
    var list = $("#signoff-blockers");
    list.innerHTML = "";
    var b = blockers();
    b.forEach(function (t) { list.appendChild(el("li", {}, t)); });
    list.hidden = !b.length;
    $("#signoff-confirm").disabled = b.length > 0;
    var total = Number($("#progress-total").textContent), done = Number($("#progress-count").textContent);
    $("#signoff-progress").textContent = done < total ? "You have given a verdict on " + done + " of " + total + " elements." : "";
    $("#signoff-name").value = state.reviewer || "";
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }
  function closeSignoff() {
    var dlg = $("#signoff-dialog");
    if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
  }
  function confirmSignoff() {
    var name = $("#signoff-name").value.trim();
    if (!name) { $("#signoff-name").focus(); return; }
    if (blockers().length) return;
    if (!state.reviewer) { state.reviewer = name; $("#reviewer").value = name; }
    state.signoff = { name: name, at: nowISO(), files: DATA.files };
    closeSignoff();
    download();
  }

  // ------------------------------------------------------------ start

  load();
  $all(".el-review").forEach(build);
  Object.keys(META).forEach(render);
  var reviewer = $("#reviewer");
  reviewer.value = state.reviewer;
  reviewer.addEventListener("input", function () { state.reviewer = reviewer.value.trim(); changed(); });
  $("#download").addEventListener("click", function () {
    if (!state.reviewer) {
      message("Please type your name first.");
      reviewer.focus();
      return;
    }
    download();
  });
  $("#signoff").addEventListener("click", openSignoff);
  $("#signoff-confirm").addEventListener("click", confirmSignoff);
  $("#signoff-cancel").addEventListener("click", closeSignoff);
  $all("button.reopen").forEach(function (b) {
    b.addEventListener("click", function () {
      var key = b.getAttribute("data-key");
      touch(key, function (c) {
        if (!c.verdict || c.verdict === "ok") c.verdict = "change";
        c.reopens = b.getAttribute("data-reopens");
      });
      var t = document.querySelector('.el-review[data-key="' + CSS.escape(key) + '"] textarea');
      if (t) t.focus();
    });
  });
  $all('input[name="filter"]').forEach(function (r) {
    r.addEventListener("change", function () { document.body.setAttribute("data-filter", r.value); });
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
  updateHeader();
  if (!storageWorks) message("");
  document.body.setAttribute("data-ready", "1");
})();
