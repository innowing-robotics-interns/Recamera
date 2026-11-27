/* Minimal Intl polyfill for Node-RED on a Node build without ICU.
 * reCamera firmware ships Node 22 with Intl disabled, which makes
 * i18next (used by the Node-RED runtime) throw "Intl is not defined".
 * This shim provides enough of the API to keep translations working. */
(function (g) {
  var I = g.Intl || {};
  g.Intl = I;
  if (!I.PluralRules) {
    I.PluralRules = function (locale, opts) {
      this._locale = String(locale || 'en').toLowerCase();
      this._type = (opts && opts.type) || 'cardinal';
    };
    I.PluralRules.prototype._cats = function () {
      return /^(zh|ja|ko|th|vi|id|ms|lo|my)/.test(this._locale) ? ['other'] : ['one', 'other'];
    };
    I.PluralRules.prototype.resolvedOptions = function () {
      return { locale: this._locale, type: this._type, pluralCategories: this._cats() };
    };
    I.PluralRules.prototype.select = function (n) {
      var v = Math.abs(Number(n));
      if (/^(zh|ja|ko|th|vi|id|ms|lo|my)/.test(this._locale)) return 'other';
      return v === 1 ? 'one' : 'other';
    };
    I.PluralRules.prototype.selectRange = function (a, b) {
      var sa = this.select(a), sb = this.select(b);
      return sa === sb ? sa : 'other';
    };
  }
  if (!I.NumberFormat) {
    I.NumberFormat = function (locale, opts) { this._opts = opts || {}; };
    I.NumberFormat.prototype.format = function (n) {
      var v = Number(n);
      if (!isFinite(v)) return String(n);
      if (this._opts && this._opts.maximumFractionDigits != null) {
        v = Number(v.toFixed(this._opts.maximumFractionDigits));
      }
      return String(v);
    };
    I.NumberFormat.prototype.formatToParts = function (n) {
      return [{ type: 'literal', value: this.format(n) }];
    };
    I.NumberFormat.prototype.resolvedOptions = function () { return { locale: 'en' }; };
  }
  if (!I.DateTimeFormat) {
    I.DateTimeFormat = function (locale, opts) { this._opts = opts || {}; };
    I.DateTimeFormat.prototype.format = function (d) {
      var t = d === undefined ? new Date() : new Date(d);
      return isNaN(t.getTime()) ? 'Invalid Date' : t.toISOString();
    };
    I.DateTimeFormat.prototype.formatToParts = function (d) {
      return [{ type: 'literal', value: this.format(d) }];
    };
    I.DateTimeFormat.prototype.resolvedOptions = function () { return { locale: 'en' }; };
  }
  if (!I.Collator) {
    I.Collator = function () {};
    I.Collator.prototype.compare = function (a, b) {
      a = String(a); b = String(b);
      return a < b ? -1 : a > b ? 1 : 0;
    };
    I.Collator.prototype.resolvedOptions = function () { return { locale: 'en' }; };
  }
  if (!I.ListFormat) {
    I.ListFormat = function () {};
    I.ListFormat.prototype.format = function (list) { return (list || []).join(', '); };
  }
  if (!I.RelativeTimeFormat) {
    I.RelativeTimeFormat = function () {};
    I.RelativeTimeFormat.prototype.format = function (v, u) { return v + ' ' + u; };
  }
  if (!I.getCanonicalLocales) {
    I.getCanonicalLocales = function (l) { return Array.isArray(l) ? l : [l]; };
  }
})(typeof globalThis !== 'undefined' ? globalThis : global);
