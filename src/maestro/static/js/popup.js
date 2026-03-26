/**
 * Shared popup primitive — positioning, show/hide, viewport clamping.
 * Used by vocab tooltips.
 */
(function() {
  'use strict';

  function Popup(el) {
    this.el = el;
  }

  Popup.prototype.show = function(anchorEl, opts) {
    opts = opts || {};
    var gap = opts.gap || 8;
    var el = this.el;
    // Make visible off-screen first to measure
    el.style.left = '0';
    el.style.top = '0';
    el.style.display = 'block';

    var r = anchorEl.getBoundingClientRect();
    var bw = el.offsetWidth;
    var bh = el.offsetHeight;

    // Vertical: prefer below, flip above if overflows
    var top = r.bottom + gap;
    if (top + bh > window.innerHeight) {
      top = r.top - bh - gap;
    }

    // Horizontal: clamp to viewport with 8px margin
    var left = Math.max(8, Math.min(r.left, window.innerWidth - bw - 8));

    el.style.top = top + 'px';
    el.style.left = left + 'px';
  };

  Popup.prototype.hide = function() {
    this.el.style.display = 'none';
  };

  Popup.prototype.isVisible = function() {
    return this.el.style.display === 'block';
  };

  /**
   * Factory: creates a Popup with delayed-hide behavior (for hover tooltips).
   * Auto-wires mouseenter/mouseleave on the popup element.
   */
  Popup.withDelayedHide = function(el, delayMs) {
    var popup = new Popup(el);
    var timer = null;

    popup.scheduleHide = function() {
      timer = setTimeout(function() { popup.hide(); }, delayMs);
    };

    popup.cancelHide = function() {
      clearTimeout(timer);
    };

    el.addEventListener('mouseenter', function() { popup.cancelHide(); });
    el.addEventListener('mouseleave', function() { popup.scheduleHide(); });

    return popup;
  };

  window.Popup = Popup;
})();
