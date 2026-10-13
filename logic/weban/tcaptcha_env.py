# -*- coding: utf-8 -*-
"""TCaptcha 纯协议求解器资源: V8 环境JS + Canvas指纹模板 + WebGL数据
（自动生成, 勿手工改; 源: build/yidun/env_v7.js + canvas_template.txt + webgl_meta.json）
"""

# V8 环境 JS(见 env_v7.js; 含 btoa/atob、navigator/screen/document 真值、魔法兜底、全内建挂载)
ENV_JS = r'''
// env_v7.js - TCaptcha 纯协议 V8 环境: 真值 + 103 API 全量假实现 + 魔法兜底
var window = globalThis;
window._t0 = Date.now();

// ============ 魔法对象: 任意属性/调用都有返回 ============
var __magicDepth = 0;
function __magic(name) {
  if (__magicDepth > 40) return '0';
  __magicDepth++;
  function target() {}
  var mp = new Proxy(target, {
    get: function (t, p) {
      if (p === Symbol.toPrimitive) return function () { return 0; };
      if (p === 'toString') return function () { return '0'; };
      if (p === 'valueOf') return function () { return 0; };
      if (p === 'length') return 0;
      if (p === 'name') return String(name);
      if (p === 'constructor') return function () {};
      if (p === Symbol.iterator) return undefined;
      if (p === 'then') return undefined;
      try { return __magic(name + '.' + String(p)); } catch (e) { return undefined; }
    },
    apply: function () { return __magic(name + '()'); },
    construct: function () { return __magic(name + '()'); },
    has: function () { return true; }
  });
  __magicDepth--;
  return mp;
}

// ============ btoa/atob ============
window.btoa = function (s) {
  var b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var r = '', i;
  for (i = 0; i < s.length; i += 3) {
    var c1 = s.charCodeAt(i), c2 = s.charCodeAt(i + 1), c3 = s.charCodeAt(i + 2);
    r += b.charAt(c1 >> 2);
    r += b.charAt(((c1 & 3) << 4) | (isNaN(c2) ? 0 : c2 >> 4));
    r += isNaN(c2) ? '=' : b.charAt(((c2 & 15) << 2) | (isNaN(c3) ? 0 : c3 >> 6));
    r += isNaN(c3) ? '=' : b.charAt(c3 & 63);
  }
  return r;
};
window.atob = function (s) {
  var b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  s = String(s).replace(/[^A-Za-z0-9+/]/g, '');
  var r = '', i = 0;
  while (i < s.length) {
    var e1 = b.indexOf(s.charAt(i++)), e2 = b.indexOf(s.charAt(i++)),
      e3 = b.indexOf(s.charAt(i++)), e4 = b.indexOf(s.charAt(i++));
    r += String.fromCharCode((e1 << 2) | (e2 >> 4));
    if (e3 !== -1) r += String.fromCharCode(((e2 & 15) << 4) | (e3 >> 2));
    if (e4 !== -1) r += String.fromCharCode(((e3 & 3) << 6) | e4);
  }
  return r;
};

// ============ 元素工厂(带魔法兜底) ============
function __makeElement(tag) {
  var el = {
    tagName: String(tag).toUpperCase(), nodeName: String(tag).toUpperCase(),
    nodeType: 1, nodeValue: null, width: 300, height: 150,
    style: { setProperty: function () {}, getPropertyValue: function () { return ''; },
             cssText: '', fontFamily: '', fontSize: '', width: '', height: '' },
    classList: { add: function () {}, remove: function () {}, contains: function () { return false; },
                 toggle: function () { return false; } },
    dataset: {}, attributes: [],
    setAttribute: function () {}, getAttribute: function () { return null; },
    removeAttribute: function () {}, hasAttribute: function () { return false; },
    appendChild: function (c) { return c; }, removeChild: function (c) { return c; },
    insertBefore: function (c) { return c; }, replaceChild: function (c) { return c; },
    remove: function () {}, cloneNode: function () { return __makeElement(tag); },
    addEventListener: function () {}, removeEventListener: function () {},
    dispatchEvent: function () { return true; },
    getContext: function () { return null; },
    toDataURL: function () { return 'data:,'; },
    toBlob: function (cb) { if (cb) cb(null); },
    getBoundingClientRect: function () { return { x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 }; },
    getClientRects: function () { return []; },
    offsetWidth: 0, offsetHeight: 0, offsetTop: 0, offsetLeft: 0, offsetParent: null,
    clientWidth: 0, clientHeight: 0, clientTop: 0, clientLeft: 0,
    scrollWidth: 0, scrollHeight: 0, scrollTop: 0, scrollLeft: 0,
    scrollIntoView: function () {},
    innerHTML: '', outerHTML: '', textContent: '', innerText: '',
    parentNode: null, parentElement: null, firstChild: null, lastChild: null,
    nextSibling: null, previousSibling: null, children: [], childNodes: [],
    src: '', href: '', currentSrc: '', complete: false, naturalWidth: 0, naturalHeight: 0,
    contentWindow: null, contentDocument: null, srcdoc: '',
    onload: null, onerror: null, onreadystatechange: null,
    focus: function () {}, blur: function () {}, click: function () {},
    value: '', checked: false, disabled: false, type: '',
    getElementsByTagName: function () { return []; },
    querySelector: function () { return null; }, querySelectorAll: function () { return []; },
    insertAdjacentHTML: function () {}, closest: function () { return null; },
    contains: function () { return false; }, matches: function () { return false; }
  };
  return new Proxy(el, {
    get: function (t, p) { if (p in t) return t[p]; return __magic(String(tag) + '.' + String(p)); },
    set: function (t, p, v) { t[p] = v; return true; },
    has: function () { return true; }
  });
}

// ============ navigator(真值 + 魔法) ============
var __nav = {
  userAgent: __UA__, appVersion: __APPV__, appName: 'Netscape',
  vendor: 'Google Inc.', vendorSub: '', platform: 'Win32', webdriver: false,
  hardwareConcurrency: 20, language: 'zh-CN', languages: ['zh-CN', 'zh'],
  cookieEnabled: true, onLine: true, product: 'Gecko', productSub: '20030107',
  appCodeName: 'Mozilla', maxTouchPoints: 0, doNotTrack: null, deviceMemory: 8,
  pdfViewerEnabled: true,
  plugins: { length: 5, item: function () { return null; }, namedItem: function () { return null; } },
  mimeTypes: { length: 2, item: function () { return null; }, namedItem: function () { return null; } },
  sendBeacon: function () { return true; },
  connection: { effectiveType: '4g', rtt: 50, downlink: 10, saveData: false,
                addEventListener: function () {}, removeEventListener: function () {} },
  userAgentData: { brands: [{ brand: 'Chromium', version: '153' }, { brand: 'Google Chrome', version: '153' }],
                   mobile: false, platform: 'Windows',
                   getHighEntropyValues: function () { return { then: function (cb) { if (cb) cb({}); } }; } },
  getBattery: function () { return { then: function () {} }; },
  permissions: { query: function () { return { then: function () {} }; } },
  mediaDevices: { enumerateDevices: function () { return { then: function () {} }; } },
  geolocation: { getCurrentPosition: function () {}, watchPosition: function () {} },
  clipboard: { writeText: function () { return { then: function () {} }; } },
  serviceWorker: { register: function () { return { then: function () {} }; }, addEventListener: function () {} },
  mimeTypes2: undefined
};
var __navP = new Proxy(__nav, {
  get: function (t, p) { if (p in t) return t[p]; return __magic('navigator.' + String(p)); },
  has: function () { return true; }
});

// ============ screen ============
var __scr = {
  width: 800, height: 600, availWidth: 800, availHeight: 600,
  availLeft: 0, availTop: 0, colorDepth: 24, pixelDepth: 24,
  orientation: { angle: 0, type: 'landscape-primary', addEventListener: function () {} },
  addEventListener: function () {}, removeEventListener: function () {}
};
var __scrP = new Proxy(__scr, {
  get: function (t, p) { if (p in t) return t[p]; return __magic('screen.' + String(p)); },
  has: function () { return true; }
});

// ============ location ============
var __loc = {
  href: __ENTRY__, protocol: 'https:', host: '__HOST__', hostname: '__HOST__',
  port: '', pathname: '/', search: '', hash: '#/course',
  origin: 'https://__HOST__', ancestorOrigins: { length: 0 },
  assign: function () {}, replace: function () {}, reload: function () {},
  toString: function () { return __ENTRY__; }
};

// ============ document ============
var __doc = {
  cookie: __COOKIE__, referrer: 'https://__HOST__/', title: '学习中心',
  domain: '__HOST__', hidden: false, visibilityState: 'visible',
  readyState: 'complete', charset: 'UTF-8', characterSet: 'UTF-8',
  inputEncoding: 'UTF-8', contentType: 'text/html', compatMode: 'CSS1Compat',
  URL: __ENTRY__, documentURI: __ENTRY__, baseURI: __ENTRY__,
  designMode: 'off', dir: 'ltr', lastModified: '01/01/2026 00:00:00',
  location: __loc, defaultView: null,
  activeElement: null,
  createElement: function (t) { return __makeElement(t); },
  createElementNS: function (ns, t) { return __makeElement(t); },
  createTextNode: function (t) { return { nodeValue: t, nodeType: 3 }; },
  createComment: function (t) { return { nodeValue: t, nodeType: 8 }; },
  createDocumentFragment: function () { return __makeElement('fragment'); },
  createEvent: function () { return { initEvent: function () {}, initCustomEvent: function () {} }; },
  createRange: function () { return __magic('range'); },
  createTreeWalker: function () { return __magic('treewalker'); },
  addEventListener: function () {}, removeEventListener: function () {},
  dispatchEvent: function () { return true; },
  getElementById: function () { return null; },
  getElementsByTagName: function () { return []; },
  getElementsByClassName: function () { return []; },
  getElementsByName: function () { return []; },
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  elementsFromPoint: function () { return []; },
  elementFromPoint: function () { return null; },
  hasFocus: function () { return true; },
  open: function () { return this; }, close: function () {},
  write: function () {}, writeln: function () {},
  execCommand: function () { return false; },
  styleSheets: { length: 0, item: function () { return null; } },
  fonts: { ready: { then: function (cb) { if (cb) cb(); } }, check: function () { return true; } },
  documentElement: __makeElement('html'),
  body: __makeElement('body'),
  head: __makeElement('head'),
  scripts: [], images: [], links: [], forms: [], anchors: [],
  all: [], children: []
};
__doc.defaultView = window;
var __docP = new Proxy(__doc, {
  get: function (t, p) { if (p in t) return t[p]; return __magic('document.' + String(p)); },
  has: function () { return true; }
});

// ============ performance(完整时间线) ============
var __perfTiming = {
  navigationStart: window._t0 - 1500, unloadEventStart: 0, unloadEventEnd: 0,
  redirectStart: 0, redirectEnd: 0, fetchStart: window._t0 - 1500,
  domainLookupStart: window._t0 - 1480, domainLookupEnd: window._t0 - 1460,
  connectStart: window._t0 - 1460, connectEnd: window._t0 - 1300,
  secureConnectionStart: window._t0 - 1400,
  requestStart: window._t0 - 1300, responseStart: window._t0 - 700,
  responseEnd: window._t0 - 650,
  domLoading: window._t0 - 620, domInteractive: window._t0 - 200,
  domContentLoadedEventStart: window._t0 - 200, domContentLoadedEventEnd: window._t0 - 180,
  domComplete: window._t0 - 100, loadEventStart: window._t0 - 100, loadEventEnd: window._t0 - 50
};
var __performance = {
  now: function () { return Date.now() - window._t0; },
  timeOrigin: window._t0 - 1500,
  timing: __perfTiming,
  navigation: { type: 0, redirectCount: 0 },
  memory: { jsHeapSizeLimit: 4294705152, totalJSHeapSize: 30000000, usedJSHeapSize: 20000000 },
  eventCounts: { size: 0 },
  getEntries: function () { return []; },
  getEntriesByType: function () { return []; },
  getEntriesByName: function () { return []; },
  mark: function () {}, measure: function () {}, clearMarks: function () {}, clearMeasures: function () {},
  measureUserAgentSpecificMemory: function () { return { then: function () {} }; },
  addEventListener: function () {}, removeEventListener: function () {}
};

// ============ crypto ============
var __crypto = {
  getRandomValues: function (a) { for (var i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256); return a; },
  randomUUID: function () {
    var h = '0123456789abcdef';
    var s = '';
    for (var i = 0; i < 36; i++) {
      if (i === 8 || i === 13 || i === 18 || i === 23) { s += '-'; continue; }
      if (i === 14) { s += '4'; continue; }
      var r = Math.floor(Math.random() * 16);
      if (i === 19) r = (r & 3) | 8;
      s += h.charAt(r);
    }
    return s;
  },
  subtle: { digest: function () { return { then: function () {} }; },
            encrypt: function () { return { then: function () {} }; },
            decrypt: function () { return { then: function () {} }; },
            generateKey: function () { return { then: function () {} }; } }
};

// ============ TextEncoder/Decoder ============
window.TextEncoder = function () {
  this.encode = function (s) {
    var out = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return new Uint8Array(out);
  };
};
window.TextDecoder = function () {
  this.decode = function (buf) {
    var s = '';
    for (var i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return s;
  };
};

// ============ 全部观察器/异步 ============
function __observerClass(name) {
  return function () {
    this.observe = function () {}; this.unobserve = function () {}; this.disconnect = function () {};
    this.takeRecords = function () { return []; };
  };
}
window.ResizeObserver = __observerClass('ResizeObserver');
window.IntersectionObserver = __observerClass('IntersectionObserver');
window.MutationObserver = __observerClass('MutationObserver');
window.PerformanceObserver = __observerClass('PerformanceObserver');
window.ReportingObserver = __observerClass('ReportingObserver');

window.queueMicrotask = function (fn) { try { fn(); } catch (e) {} };
window.requestIdleCallback = function (cb) { return setTimeout(function () { cb({ didTimeout: false, timeRemaining: function () { return 50; } }); }, 16); };
window.cancelIdleCallback = function (id) { clearTimeout(id); };
window.structuredClone = function (o) { try { return JSON.parse(JSON.stringify(o)); } catch (e) { return o; } };
window.scheduler = { postTask: function () { return { then: function () {} }; }, yield: function () { return { then: function () {} }; } };

// ============ 网络(魔法兜底级) ============
window.fetch = function () { return __magic('fetch()'); };
window.XMLHttpRequest = function () {
  this.open = function () {}; this.send = function () {}; this.setRequestHeader = function () {};
  this.addEventListener = function () {}; this.abort = function () {};
  this.getAllResponseHeaders = function () { return ''; }; this.getResponseHeader = function () { return null; };
  this.readyState = 0; this.status = 0; this.responseText = ''; this.response = '';
};
window.WebSocket = function () {
  this.send = function () {}; this.close = function () {}; this.addEventListener = function () {};
  this.readyState = 0;
};
window.EventSource = function () { this.close = function () {}; this.addEventListener = function () {}; };
window.Request = function () { return __magic('Request'); };
window.Response = function () { return __magic('Response'); };
window.Headers = function () { this.append = function () {}; this.get = function () { return null; }; };
window.FormData = function () { this.append = function () {}; };
window.URLSearchParams = function (init) {
  this._d = {};
  this.append = function (k, v) { this._d[k] = v; };
  this.get = function (k) { return this._d[k] || null; };
  this.toString = function () { var p = []; for (var k in this._d) p.push(encodeURIComponent(k) + '=' + encodeURIComponent(this._d[k])); return p.join('&'); };
};
window.URL = function (u, base) {
  this.href = u || ''; this.origin = 'https://__HOST__';
  this.protocol = 'https:'; this.host = '__HOST__'; this.hostname = '__HOST__';
  this.pathname = '/'; this.search = ''; this.hash = '';
  this.toString = function () { return this.href; };
  this.createObjectURL = function () { return 'blob:https://__HOST__/x'; };
  this.revokeObjectURL = function () {};
};
window.URL.createObjectURL = function () { return 'blob:https://__HOST__/x'; };
window.URL.revokeObjectURL = function () {};
window.URLPattern = function () { return __magic('URLPattern'); };
window.AbortController = function () { this.abort = function () {}; this.signal = { aborted: false, addEventListener: function () {} }; };
window.AbortSignal = { timeout: function () { return { aborted: false }; }, abort: function () { return { aborted: true }; } };
window.RTCPeerConnection = function () { this.createOffer = function () { return { then: function () {} }; }; this.close = function () {}; };

// ============ 图形 ============
window.OffscreenCanvas = function (w, h) { this.width = w; this.height = h; this.getContext = function () { return null; }; };
window.createImageBitmap = function () { return { then: function () {} }; };
window.ImageBitmap = function () {};
window.ImageData = function (w, h) { this.width = w; this.height = h; this.data = new Uint8ClampedArray(w * h * 4); };
window.Path2D = function () { this.arc = function () {}; this.rect = function () {}; this.moveTo = function () {}; this.lineTo = function () {}; };
window.WebGLRenderingContext = function () {};
window.WebGL2RenderingContext = function () {};
window.CanvasRenderingContext2D = function () {};
window.HTMLCanvasElement = function () {};
window.Image = function () { return __makeElement('img'); };
window.Audio = function () { return __makeElement('audio'); };
window.AudioContext = function () { this.createOscillator = function () { return { connect: function () {}, start: function () {} }; }; this.createGain = function () { return { connect: function () {} }; }; this.destination = {}; this.close = function () {}; };
window.OfflineAudioContext = function () { this.startRendering = function () { return { then: function () {} }; }; this.createOscillator = function () { return {}; }; this.destination = {}; };

// ============ DOM 类家族 ============
function __cls(name) { var f = function () {}; f.toString = function () { return 'function ' + name + '() { [native code] }'; }; return f; }
window.Node = __cls('Node');
window.Element = __cls('Element');
window.HTMLElement = __cls('HTMLElement');
window.HTMLIFrameElement = __cls('HTMLIFrameElement');
window.HTMLDivElement = __cls('HTMLDivElement');
window.HTMLSpanElement = __cls('HTMLSpanElement');
window.HTMLParagraphElement = __cls('HTMLParagraphElement');
window.HTMLStyleElement = __cls('HTMLStyleElement');
window.HTMLImageElement = __cls('HTMLImageElement');
window.HTMLScriptElement = __cls('HTMLScriptElement');
window.HTMLAnchorElement = __cls('HTMLAnchorElement');
window.Event = function (type) { this.type = type; this.target = null; this.preventDefault = function () {}; this.stopPropagation = function () {}; };
window.CustomEvent = function (type, opts) { this.type = type; this.detail = (opts || {}).detail; };
window.MouseEvent = function (type, opts) { this.type = type; this.clientX = 0; this.clientY = 0; };
window.KeyboardEvent = function (type) { this.type = type; };
window.TouchEvent = function (type) { this.type = type; };
window.PointerEvent = function (type) { this.type = type; };
window.WheelEvent = function (type) { this.type = type; };
window.DOMParser = function () { this.parseFromString = function () { return __makeElement('html'); }; };
window.XMLSerializer = function () { this.serializeToString = function () { return ''; }; };

// ============ 存储 ============
window.localStorage = { length: 0, getItem: function () { return null; }, setItem: function () {}, removeItem: function () {}, clear: function () {}, key: function () { return null; } };
window.sessionStorage = { length: 0, getItem: function () { return null; }, setItem: function () {}, removeItem: function () {}, clear: function () {} };
window.indexedDB = { open: function () { return __magic('idb-open'); }, deleteDatabase: function () { return __magic('idb-del'); } };
window.caches = { open: function () { return { then: function () {} }; }, keys: function () { return { then: function () {} }; } };

// ============ 杂项 ============
window.chrome = { runtime: {}, loadTimes: function () { return {}; }, csi: function () { return {}; }, app: { isInstalled: false } };
window.crossOriginIsolated = false;
window.isSecureContext = true;
window.devicePixelRatio = 1;
window.outerWidth = 800; window.outerHeight = 600;
window.innerWidth = 800; window.innerHeight = 600;
window.screenX = 0; window.screenY = 0; window.screenLeft = 0; window.screenTop = 0;
window.pageXOffset = 0; window.pageYOffset = 0; window.scrollX = 0; window.scrollY = 0;
window.toolbar = { visible: true }; window.menubar = { visible: true };
window.personalbar = { visible: true }; window.scrollbars = { visible: true };
window.locationbar = { visible: true }; window.statusbar = { visible: true };
window.speechSynthesis = { getVoices: function () { return []; }, speak: function () {}, cancel: function () {} };
window.visualViewport = { width: 800, height: 600, scale: 1, offsetLeft: 0, offsetTop: 0, addEventListener: function () {} };
window.external = { AddSearchProvider: function () {}, IsSearchProviderInstalled: function () { return 0; } };
window.history = { length: 2, scrollRestoration: 'auto', state: null, pushState: function () {}, replaceState: function () {}, back: function () {}, forward: function () {}, go: function () {} };
window.getSelection = function () { return { toString: function () { return ''; }, removeAllRanges: function () {}, addRange: function () {} }; };
window.matchMedia = function () { return { matches: false, media: '', addListener: function () {}, removeListener: function () {}, addEventListener: function () {}, removeEventListener: function () {} }; };
window.scrollTo = function () {}; window.scrollBy = function () {}; window.scroll = function () {};
window.alert = function () {}; window.confirm = function () { return true; }; window.prompt = function () { return null; };
window.open = function () { return null; }; window.close = function () {}; window.print = function () {}; window.stop = function () {};
window.addEventListener = function () {}; window.removeEventListener = function () {}; window.dispatchEvent = function () { return true; };
window.attachEvent = undefined;
window.requestAnimationFrame = function (cb) { return setTimeout(function () { cb(Date.now()); }, 16); };
window.cancelAnimationFrame = function (id) { clearTimeout(id); };
window.getComputedStyle = function () {
  return { fontFamily: '', width: '0px', height: '0px', fontSize: '0px', lineHeight: '0px',
           getPropertyValue: function () { return ''; } };
};
window.Blob = function (parts, opts) { this.size = 0; this.type = (opts || {}).type || ''; this.slice = function () { return this; }; };
window.File = function (parts, name, opts) { this.name = name; this.size = 0; this.type = ''; };
window.FileReader = function () { this.readAsDataURL = function () {}; this.readAsText = function () {}; this.addEventListener = function () {}; this.result = null; };
window.FileList = function () { this.length = 0; };
window.Notification = function () {}; window.Notification.permission = 'default'; window.Notification.requestPermission = function () { return { then: function () {} }; };
window.Worker = function () { this.postMessage = function () {}; this.terminate = function () {}; this.addEventListener = function () {}; };
window.SharedWorker = window.Worker;
window.ServiceWorker = window.Worker;

// ============ 组装 window ============
var __win = {
  navigator: __navP, screen: __scrP, location: __loc, document: __docP,
  performance: __performance, crypto: __crypto,
  localStorage: window.localStorage, sessionStorage: window.sessionStorage,
  history: window.history, devicePixelRatio: 1,
  outerWidth: 800, outerHeight: 600, innerWidth: 800, innerHeight: 600,
  screenX: 0, screenY: 0, pageXOffset: 0, pageYOffset: 0, scrollX: 0, scrollY: 0,
  addEventListener: window.addEventListener, removeEventListener: window.removeEventListener,
  dispatchEvent: window.dispatchEvent,
  getComputedStyle: window.getComputedStyle, matchMedia: window.matchMedia,
  XMLHttpRequest: window.XMLHttpRequest, requestAnimationFrame: window.requestAnimationFrame,
  cancelAnimationFrame: window.cancelAnimationFrame,
  Image: window.Image, Audio: window.Audio,
  fetch: window.fetch, WebSocket: window.WebSocket,
  chrome: window.chrome, isSecureContext: true, crossOriginIsolated: false,
  toolbar: window.toolbar, menubar: window.menubar, personalbar: window.personalbar,
  scrollbars: window.scrollbars, locationbar: window.locationbar, statusbar: window.statusbar,
  speechSynthesis: window.speechSynthesis, visualViewport: window.visualViewport,
  external: window.external, getSelection: window.getSelection,
  scrollTo: window.scrollTo, scrollBy: window.scrollBy, scroll: window.scroll,
  alert: window.alert, confirm: window.confirm, prompt: window.prompt,
  open: window.open, close: window.close, print: window.print, stop: window.stop,
  setTimeout: setTimeout, clearTimeout: clearTimeout, setInterval: setTimeout,
  Date: Date, Math: Math, JSON: JSON, Object: Object, Array: Array, String: String,
  Number: Number, Boolean: Boolean, RegExp: RegExp, Error: Error, Function: Function
};
__win.window = __win; __win.self = __win; __win.top = __win; __win.parent = __win;
__win.globalThis = __win; __win.frames = __win; __win.length = 0; __win.name = '';

// 顶层: window = 万能 Proxy(未知属性 = 内建 > __win > 魔法)
globalThis.window = new Proxy(__win, {
  get: function (t, p) {
    if (p in t) return t[p];
    if (p in globalThis) return globalThis[p];
    return __magic('window.' + String(p));
  },
  set: function (t, p, v) { t[p] = v; try { globalThis[p] = v; } catch (e) {} return true; },
  has: function () { return true; }
});
'''

# 假 Canvas/WebGL 注入 JS(模板占位符在求解器中替换)
FAKE_CANVAS_JS = r'''
var __WEBGL_EXTS = __EXTS__;
var __VENDOR = __VENDOR__;
var __RENDERER = __RENDERER__;
var __CANVAS_DATAURL = __DATAURL__;
var __fakeWebGL = new Proxy({
  getSupportedExtensions: function() { return __WEBGL_EXTS.slice(); },
  getExtension: function(name) {
    if (String(name) === 'WEBGL_debug_renderer_info') {
      return { UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 };
    }
    return null;
  },
  getParameter: function(p) {
    if (p === 37445) return __VENDOR;
    if (p === 37446) return __RENDERER;
    return 0;
  },
  getShaderPrecisionFormat: function() { return { rangeMin: 127, rangeMax: 127, precision: 23 }; }
}, { get: function(t, p) { if (p in t) return t[p]; return function() { return 0; }; } });
var __fake2D = new Proxy({
  toDataURL: function() { return __CANVAS_DATAURL; },
  getImageData: function(x, y, w, h) { return { width: w||1, height: h||1, data: new Uint8ClampedArray((w||1)*(h||1)*4) }; },
  measureText: function() { return { width: 10 }; },
  isPointInPath: function() { return false; }, isPointInStroke: function() { return false; },
  createLinearGradient: function() { return { addColorStop: function() {} }; },
  createRadialGradient: function() { return { addColorStop: function() {} }; }
}, { get: function(t, p) { if (p in t) return t[p]; return function() {}; }, set: function() { return true; } });
var __origMakeElement = __makeElement;
__makeElement = function(tag) {
  var el = __origMakeElement(tag);
  if (String(tag).toLowerCase() === 'canvas') {
    try {
      el.width = 300; el.height = 150;
      el.getContext = function(type) {
        var s = String(type);
        if (s.indexOf('webgl') >= 0) return __fakeWebGL;
        if (s === '2d') return __fake2D;
        return null;
      };
      el.toDataURL = function() { return __CANVAS_DATAURL; };
    } catch (e) {}
  }
  return el;
};
'''

# 真实浏览器采集的 Canvas 指纹 dataURL(8294 字符, 300x150 PNG)
CANVAS_DATAURL = 'data:image/png;base64,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'

# WebGL 元数据(35 扩展 + GPU 供应商/渲染器)
WEBGL_EXTS = ["ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_clip_control", "EXT_color_buffer_half_float", "EXT_depth_clamp", "EXT_disjoint_timer_query", "EXT_float_blend", "EXT_frag_depth", "EXT_polygon_offset_clamp", "EXT_shader_texture_lod", "EXT_texture_compression_bptc", "EXT_texture_compression_rgtc", "EXT_texture_filter_anisotropic", "EXT_texture_mirror_clamp_to_edge", "EXT_sRGB", "KHR_parallel_shader_compile", "OES_element_index_uint", "OES_fbo_render_mipmap", "OES_standard_derivatives", "OES_texture_float", "OES_texture_float_linear", "OES_texture_half_float", "OES_texture_half_float_linear", "OES_vertex_array_object", "WEBGL_blend_func_extended", "WEBGL_color_buffer_float", "WEBGL_compressed_texture_s3tc", "WEBGL_compressed_texture_s3tc_srgb", "WEBGL_debug_renderer_info", "WEBGL_debug_shaders", "WEBGL_depth_texture", "WEBGL_draw_buffers", "WEBGL_lose_context", "WEBGL_multi_draw", "WEBGL_polygon_mode"]
WEBGL_VENDOR = "Google Inc. (Intel)"
WEBGL_RENDERER = "ANGLE (Intel, Intel(R) UHD Graphics (0x0000A78B) Direct3D11 vs_5_0 ps_5_0, D3D11)"
