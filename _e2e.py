"""Pruebas E2E TEMPORALES del panel privado (Chrome real + CDP).

NO forma parte del proyecto: se elimina al terminar.
Ejecuta la funcion real (netlify/functions/panel-data.js) dentro de Chrome con
shims de Node y prueba el flujo completo de panel.html (login, graficas, tabla, CSV).
"""
import asyncio
import csv
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import websockets

ROOT = Path(__file__).resolve().parent
PANEL_HTML = (ROOT / "panel.html").read_text(encoding="utf-8")
FN_SRC = (ROOT / "netlify" / "functions" / "panel-data.js").read_text(encoding="utf-8")

ANON_KEY = "sb_publishable_a3dXjRpitFszJWvJgM-yvw_gvfszpS4"
SUPABASE_URL = "https://xndkpvsnlmyunlnqkrwf.supabase.co"
PASSWORD = "clave-e2e-2026"
SERVICE_KEY_DUMMY = "sb_secret_clave-de-servicio-simulada-000"
DOWNLOAD_DIR = ROOT / "_e2e_downloads"

FIXTURE = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2026-09-25T14:35:00+00:00",
        "nombre": "Ana Gómez Restrepo",
        "celular": "3001234567",
        "respuestas": {
            "comuna": "Belen",
            "referido_por": "Ana Gómez",
            "le_gusta": "Seguridad",
            "problema_principal": "Movilidad/trafico",
            "seguridad_nocturna": "Poco seguro/a",
            "propuesta_cambio": "Más cámaras de seguridad en los parques",
            "quiere_contacto": "Si",
        },
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "created_at": "2026-09-24T09:10:00+00:00",
        "nombre": "Carlos Ruiz",
        "celular": "3105557788",
        "respuestas": {
            "comuna": "Belen",
            "referido_por": "",
            "le_gusta": "Cultura y eventos",
            "problema_principal": "Seguridad",
            "seguridad_nocturna": "Nada seguro/a",
            "propuesta_cambio": "Mejorar el alumbrado publico",
            "quiere_contacto": "No",
        },
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "created_at": "2026-09-23T18:00:00+00:00",
        "nombre": "María López",
        "celular": "3214442211",
        "respuestas": {
            "comuna": "El Poblado",
            "le_gusta": "Espacios publicos y parques",
            "problema_principal": "Seguridad",
            "seguridad_nocturna": "Muy seguro/a",
            "propuesta_cambio": 'Poner "comillas" y ; punto y coma\ncon salto',
            "quiere_contacto": "Si",
        },
    },
    {
        "id": "44444444-4444-4444-4444-444444444444",
        "created_at": "2026-09-22T07:45:00+00:00",
        "nombre": 'Prueba <img src=x onerror="window.__xss=1">',
        "celular": "",
        "respuestas": None,
    },
]

JS_SHIM = r"""
(function () {
  /* ===== HARNESS E2E TEMPORAL (no forma parte del proyecto) ===== */
  var FIXTURE = __FIXTURE__;
  var mode = 'fixture';

  /* Polyfill minimo de Buffer/crypto para ejecutar la funcion real en Chrome */
  Uint8Array.prototype.copy = function (target, targetStart) {
    target.set(this, targetStart || 0);
    return target;
  };
  window.Buffer = {
    from: function (value, enc) {
      var texto = String(value);
      var bytes;
      if (enc === 'base64') {
        var bin = atob(texto);
        bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
      } else {
        bytes = new TextEncoder().encode(texto);
      }
      bytes.toString = function () { return new TextDecoder().decode(this); };
      return bytes;
    },
    alloc: function (n) { return new Uint8Array(n); }
  };
  window.require = function (name) {
    if (name === 'crypto') {
      return {
        timingSafeEqual: function (a, b) {
          if (!a || !b || a.length !== b.length) return false;
          var diff = 0;
          for (var i = 0; i < a.length; i++) { diff |= a[i] ^ b[i]; }
          return diff === 0;
        }
      };
    }
    throw new Error('require no soportado en el harness: ' + name);
  };
  window.process = {
    env: {
      PANEL_PASSWORD: __PASSWORD__,
      SUPABASE_URL: __SUPABASE_URL__,
      SUPABASE_SERVICE_ROLE_KEY: __SERVICE_KEY__
    }
  };
  window.exports = {};

  window.__panel = {
    fetchLog: [],
    supabaseCalls: [],
    csv: null,
    setMode: function (m) { mode = m; },
    getMode: function () { return mode; },
    setEnv: function (patch) {
      Object.keys(patch).forEach(function (k) {
        if (patch[k] === null) { delete window.process.env[k]; }
        else { window.process.env[k] = patch[k]; }
      });
    },
    resetFetchLog: function () { window.__panel.fetchLog = []; window.__panel.supabaseCalls = []; },
    handler: null
  };

  var nativeFetch = window.fetch.bind(window);
  window.fetch = function (url, options) {
    options = options || {};
    var target = String(url);
    if (target.indexOf('/.netlify/functions/panel-data') !== -1) {
      window.__panel.fetchLog.push({ url: target, method: options.method, body: options.body });
      return window.__panel.handler({ httpMethod: options.method, body: options.body }).then(function (res) {
        return new Response(res.body, { status: res.statusCode, headers: res.headers });
      });
    }
    /* Llamada de la funcion a Supabase (PostgREST) */
    window.__panel.supabaseCalls.push({ url: target, options: options });
    if (mode === 'real') { return nativeFetch(url, options); }
    if (mode === 'empty') {
      return Promise.resolve(new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (mode === 'error') {
      return Promise.resolve(new Response('{"message":"boom-upstream"}', { status: 500 }));
    }
    if (mode === 'no-array') {
      return Promise.resolve(new Response('{"message":"estructura-rara"}', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (mode === 'timeout') {
      return new Promise(function (resolve, reject) {
        if (options.signal) {
          options.signal.addEventListener('abort', function () {
            var err = new Error('The operation was aborted.');
            err.name = 'AbortError';
            reject(err);
          });
        }
      });
    }
    return Promise.resolve(new Response(JSON.stringify(FIXTURE), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    }));
  };

  /* Captura del CSV generado por el boton Exportar */
  var nativeCreateObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (blob) {
    if (window.Blob && blob instanceof Blob && String(blob.type).indexOf('text/csv') === 0) {
      blob.text().then(function (txt) { window.__panel.csv = txt; });
    }
    return nativeCreateObjectURL(blob);
  };
  var nativeCreateElement = document.createElement.bind(document);
  document.createElement = function (tag) {
    var node = nativeCreateElement(tag);
    if (String(tag).toLowerCase() === 'a') {
      var clickOriginal = node.click.bind(node);
      node.click = function () { window.__panel.lastDownloadName = node.download; clickOriginal(); };
    }
    return node;
  };
})();
"""


JS_UI_TESTS_A = r"""
window.__runUiTests = async function () {
  var checks = [];
  function check(name, ok, detail) {
    checks.push({ name: name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function waitFor(fn, timeoutMs) {
    var inicio = Date.now();
    while (Date.now() - inicio < (timeoutMs || 6000)) {
      try { if (fn()) return true; } catch (e) { /* sigue esperando */ }
      await sleep(50);
    }
    return false;
  }
  function el(id) { return document.getElementById(id); }
  function visible(node) { return !!node && !node.hidden && node.offsetParent !== null; }
  function chart(id) { return (typeof Chart !== 'undefined') ? Chart.getChart(el(id)) : undefined; }
  function chartData(id) {
    var g = chart(id);
    if (!g) return null;
    return { labels: g.data.labels.slice(), data: g.data.datasets[0].data.slice(), tipo: g.config.type };
  }
  function filasTabla() {
    return Array.prototype.slice.call(document.querySelectorAll('#responses-tbody tr')).map(function (tr) {
      return Array.prototype.slice.call(tr.children).map(function (td) { return td.textContent.trim(); });
    });
  }
  function enviar(password) {
    el('password-input').value = password;
    el('login-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
  }

  /* 1. Estado inicial: solo el formulario de acceso */
  check('Chart.js cargado desde CDN', typeof Chart !== 'undefined' && typeof Chart.version === 'string', typeof Chart !== 'undefined' ? Chart.version : 'no disponible');
  check('Vista de datos oculta al cargar', !visible(el('dashboard-view')) && !visible(el('table-card')) && !visible(el('charts-grid')));
  check('Formulario de acceso visible', visible(el('login-form')) && visible(el('password-input')) && visible(el('btn-login')));
  check('Sin datos en pantalla al cargar', el('responses-tbody').children.length === 0 && el('kpi-total').textContent.trim() === '0');
  check('Sin botones de sesion antes de ingresar', !visible(el('panel-actions')));
  check('Nada en localStorage/sessionStorage', window.localStorage.length === 0 && window.sessionStorage.length === 0);

  /* 2. Envio vacio */
  enviar('');
  var avisoVacio = await waitFor(function () { return /Escribe la contrase/i.test(el('login-alert').textContent); }, 3000);
  check('Contrasena vacia: pide escribirla', avisoVacio, el('login-alert').textContent.trim());
  check('Sin contrasena no se ven datos', !visible(el('dashboard-view')));

  /* 3. Contrasena incorrecta (401 del servidor) */
  enviar('clave-equivocada');
  var avisoError = await waitFor(function () { return /Contrase\u00f1a incorrecta/.test(el('login-alert').textContent); }, 8000);
  check('Contrasena incorrecta: mensaje del servidor', avisoError, el('login-alert').textContent.trim());
  check('Contrasena incorrecta: panel sigue bloqueado', !visible(el('dashboard-view')) && visible(el('login-form')));
  check('Contrasena incorrecta: permite reintentar', el('password-input').value === '' && el('password-input').readOnly === false);
  check('Contrasena incorrecta: banner de error del sistema de diseno', !!document.querySelector('#login-alert .alert-banner.alert-error'));

  /* 4. Contrasena correcta */
  enviar('clave-e2e-2026');
  var abierto = await waitFor(function () { return visible(el('dashboard-view')) && el('responses-tbody').children.length === 4; }, 10000);
  check('Contrasena correcta: se abre el panel', abierto);
  var ultimo = window.__panel.fetchLog[window.__panel.fetchLog.length - 1];
  var payloadOk = false;
  try { payloadOk = JSON.parse(ultimo.body).password === 'clave-e2e-2026'; } catch (e) { payloadOk = false; }
  check('POST a /.netlify/functions/panel-data con { password }', ultimo && ultimo.url === '/.netlify/functions/panel-data' && ultimo.method === 'POST' && payloadOk, ultimo ? ultimo.url + ' ' + ultimo.method : 'sin registro');
  check('Login oculto tras ingresar', !visible(el('login-form')));
  check('Input de contrasena vaciado tras ingresar', el('password-input').value === '');
  check('Botones Actualizar/Salir visibles', visible(el('panel-actions')));

  /* 5. Contador y graficas */
  check('Contador total = 4', el('kpi-total').textContent.trim() === '4', el('kpi-total').textContent.trim());
  check('Titulo de la tabla con el total', el('table-count').textContent.trim() === '4');
  check('Estado vacio oculto', !visible(el('dashboard-empty')));
  var comuna = chartData('chart-comuna');
  check('Grafica de comuna: barra', comuna && comuna.tipo === 'bar');
  check('Grafica de comuna: datos correctos', comuna && JSON.stringify(comuna.labels) === JSON.stringify(['Belen', 'El Poblado', 'Sin dato']) && JSON.stringify(comuna.data) === JSON.stringify([2, 1, 1]), comuna ? JSON.stringify(comuna.labels) + ' -> ' + JSON.stringify(comuna.data) : 'sin grafica');
  var problema = chartData('chart-problema');
  check('Grafica de problema principal: barra horizontal', problema && problema.tipo === 'bar' && chart('chart-problema').options.indexAxis === 'y');
  check('Grafica de problema principal: datos correctos', problema && JSON.stringify(problema.labels) === JSON.stringify(['Seguridad', 'Movilidad/trafico', 'Sin dato']) && JSON.stringify(problema.data) === JSON.stringify([2, 1, 1]), problema ? JSON.stringify(problema.labels) + ' -> ' + JSON.stringify(problema.data) : 'sin grafica');
  var seguridad = chartData('chart-seguridad');
  check('Grafica de seguridad: dona', seguridad && seguridad.tipo === 'doughnut');
  check('Grafica de seguridad: 4 opciones + Sin dato', seguridad && JSON.stringify(seguridad.labels) === JSON.stringify(['Muy seguro/a', 'Nada seguro/a', 'Poco seguro/a', 'Sin dato', 'Algo seguro/a']), seguridad ? JSON.stringify(seguridad.labels) : 'sin grafica');
  check('Grafica de seguridad: suma = total de respuestas', seguridad && seguridad.data.reduce(function (a, b) { return a + b; }, 0) === 4, seguridad ? JSON.stringify(seguridad.data) : '');
  check('Canvas de las 3 graficas con tamano real', ['chart-comuna', 'chart-problema', 'chart-seguridad'].every(function (id) { var c = el(id); return c && c.width > 0 && c.height > 0; }));
  check('Contenedor de graficas visible', visible(el('charts-grid')));

  /* 6. Tabla */
  var filas = filasTabla();
  check('Tabla: 4 filas', filas.length === 4, filas.length);
  check('Tabla: 10 columnas por fila', filas.every(function (f) { return f.length === 10; }));
  check('Tabla: fila 1 con acentos y valores correctos', JSON.stringify(filas[0].slice(0, 9)) === JSON.stringify(['Ana G\u00f3mez Restrepo', '3001234567', 'Belen', 'Ana G\u00f3mez', 'Seguridad', 'Movilidad/trafico', 'Poco seguro/a', 'M\u00e1s c\u00e1maras de seguridad en los parques', 'Si']), JSON.stringify(filas[0]));
  check('Tabla: fila 4 vacia -> "Sin dato"', filas[3].slice(1, 9).join('|') === 'Sin dato|Sin dato|Sin dato|Sin dato|Sin dato|Sin dato|Sin dato|Sin dato', JSON.stringify(filas[3]));
  check('Tabla: HTML escapado (sin XSS)', window.__xss === undefined && document.querySelectorAll('#responses-tbody img').length === 0 && el('responses-tbody').innerHTML.indexOf('&lt;img') !== -1);
  check('Tabla: contenedor con scroll horizontal', (function () { var w = document.querySelector('.table-scroll'); return !!w && getComputedStyle(w).overflowX === 'auto'; })());
  check('Boton exportar habilitado con datos', el('btn-export').disabled === false);

  /* 7. Actualizar */
  var antes = window.__panel.fetchLog.length;
  el('btn-refresh').click();
  var refresco = await waitFor(function () { return window.__panel.fetchLog.length > antes && el('responses-tbody').children.length === 4; }, 8000);
  check('Boton Actualizar vuelve a consultar los datos', refresco && el('kpi-total').textContent.trim() === '4');

  /* 8. Exportar a CSV */
  el('btn-export').click();
  var csvListo = await waitFor(function () { return window.__panel.csv !== null; }, 6000);
  check('Exportar: se genero el CSV en el navegador', csvListo && typeof window.__panel.csv === 'string' && window.__panel.csv.length > 100, window.__panel.csv ? window.__panel.csv.length + ' chars' : 'sin CSV');
  check('Exportar: encabezado al inicio del CSV', !!window.__panel.csv && window.__panel.csv.replace('\uFEFF', '').indexOf('"Nombre";"Celular"') === 0, window.__panel.csv ? window.__panel.csv.slice(0, 40) : 'sin CSV');
  check('Exportar: nombre de archivo .csv', /^respuestas-sebas-lopez-\d{4}-\d{2}-\d{2}\.csv$/.test(String(window.__panel.lastDownloadName)), window.__panel.lastDownloadName);

  /* 9. Salir */
  el('btn-logout').click();
  var salio = await waitFor(function () { return visible(el('login-form')); }, 5000);
  check('Salir: vuelve al formulario de acceso', salio && !visible(el('dashboard-view')) && !visible(el('panel-actions')));
  check('Salir: datos limpiados de la pantalla', el('responses-tbody').children.length === 0 && el('kpi-total').textContent.trim() === '0' && el('table-card').hidden === true);
  check('Salir: graficas destruidas', chart('chart-comuna') === undefined && chart('chart-problema') === undefined && chart('chart-seguridad') === undefined);
  check('Salir: nada guardado en el navegador', window.localStorage.length === 0 && window.sessionStorage.length === 0);

  /* 10. Estado vacio (sin respuestas en la base) */
  window.__panel.setMode('empty');
  enviar('clave-e2e-2026');
  var vacio = await waitFor(function () { return visible(el('dashboard-empty')); }, 8000);
  check('Sin respuestas: mensaje de estado vacio', vacio && visible(el('dashboard-view')));
  check('Sin respuestas: sin graficas, sin tabla y exportar deshabilitado', !visible(el('charts-grid')) && !visible(el('table-card')) && el('btn-export').disabled === true);
  check('Sin respuestas: contador en 0', el('kpi-total').textContent.trim() === '0');
  window.__panel.setMode('fixture');

  return checks;
};
"""

JS_UNIT_TESTS = r"""
window.__runUnitTests = async function () {
  var checks = [];
  function check(name, ok, detail) {
    checks.push({ name: name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });
  }
  var P = window.__panel;
  var handler = P.handler;
  var SERVICE_KEY = window.process.env.SUPABASE_SERVICE_ROLE_KEY;

  async function call(event) {
    var res = await handler(event);
    var body = null;
    try { body = JSON.parse(res.body); } catch (e) { body = null; }
    return { status: res.statusCode, body: body, raw: res.body, headers: res.headers };
  }
  function post(payload) {
    return call({ httpMethod: 'POST', body: typeof payload === 'string' ? payload : JSON.stringify(payload) });
  }

  /* Metodo HTTP */
  var get = await call({ httpMethod: 'GET' });
  check('GET -> 405 Metodo no permitido', get.status === 405 && get.body && get.body.error === 'M\u00e9todo no permitido', get.status + ' ' + get.raw);
  var put = await call({ httpMethod: 'PUT', body: '{}' });
  check('PUT -> 405', put.status === 405, String(put.status));

  /* Body invalido */
  var sinBody = await call({ httpMethod: 'POST' });
  check('POST sin body -> 400 Solicitud invalida', sinBody.status === 400 && sinBody.body && sinBody.body.error === 'Solicitud inv\u00e1lida', sinBody.status + ' ' + sinBody.raw);
  var jsonMalo = await post('esto-no-es-json');
  check('POST con JSON invalido -> 400', jsonMalo.status === 400, String(jsonMalo.status));
  var arreglo = await post('[1,2,3]');
  check('POST con JSON que no es objeto -> 400', arreglo.status === 400, String(arreglo.status));

  /* Contrasena */
  var vacia = await post({});
  check('Sin password -> 401 Contrasena incorrecta', vacia.status === 401 && vacia.body.error === 'Contrase\u00f1a incorrecta', vacia.status + ' ' + vacia.raw);
  var mala = await post({ password: 'otra-clave' });
  check('Password incorrecta -> 401', mala.status === 401, String(mala.status));
  var tipoMalo = await post({ password: 12345 });
  check('Password que no es string -> 401', tipoMalo.status === 401, String(tipoMalo.status));
  var b64 = await call({ httpMethod: 'POST', isBase64Encoded: true, body: btoa('{"password":"clave-e2e-2026"}') });
  check('Body en base64 -> 200', b64.status === 200 && Array.isArray(b64.body.data), String(b64.status));

  /* Camino feliz: forma de la respuesta, cabeceras y consulta a Supabase */
  P.resetFetchLog();
  var ok = await post({ password: 'clave-e2e-2026' });
  check('Password correcta -> 200 { data: [...] }', ok.status === 200 && Array.isArray(ok.body.data) && ok.body.data.length === 4 && Object.keys(ok.body).join(',') === 'data', ok.status + ' keys=' + Object.keys(ok.body).join(','));
  check('Cabeceras: no-store + JSON', String(ok.headers['Cache-Control']).indexOf('no-store') === 0 && String(ok.headers['Content-Type']).indexOf('application/json') === 0, JSON.stringify(ok.headers));
  var llamada = P.supabaseCalls[P.supabaseCalls.length - 1];
  var u = new URL(llamada.url);
  check('Consulta a /rest/v1/respuestas del proyecto', u.pathname === '/rest/v1/respuestas' && u.host === 'xndkpvsnlmyunlnqkrwf.supabase.co', u.pathname + ' @ ' + u.host);
  check('select = 5 columnas pedidas', u.searchParams.get('select') === 'id,created_at,nombre,celular,respuestas', String(u.searchParams.get('select')));
  check('order = created_at.desc', u.searchParams.get('order') === 'created_at.desc', String(u.searchParams.get('order')));
  check('Metodo GET contra Supabase', llamada.options.method === 'GET', String(llamada.options.method));
  check('Header apikey con la service_role', llamada.options.headers.apikey === SERVICE_KEY);
  check('Header Authorization: Bearer service_role', llamada.options.headers.Authorization === 'Bearer ' + SERVICE_KEY);
  check('Header Accept: application/json', llamada.options.headers.Accept === 'application/json');
  check('Timeout por AbortSignal configurado', !!llamada.options.signal);
  check('La respuesta no expone la service_role key', ok.raw.indexOf(SERVICE_KEY) === -1);
  check('La respuesta no expone nombres de variables de entorno', ok.raw.indexOf('SUPABASE') === -1 && ok.raw.indexOf('PANEL_PASSWORD') === -1);

  /* Supabase caido o con estructura rara */
  P.setMode('error');
  var caido = await post({ password: 'clave-e2e-2026' });
  check('Supabase 500 -> 502 con mensaje generico', caido.status === 502 && /No se pudieron obtener las respuestas/.test(caido.body.error), caido.status + ' ' + caido.raw);
  check('Supabase 500: no filtra el detalle interno', caido.raw.indexOf('boom-upstream') === -1 && caido.raw.indexOf(SERVICE_KEY) === -1);
  P.setMode('no-array');
  var raro = await post({ password: 'clave-e2e-2026' });
  check('Respuesta que no es arreglo -> 502', raro.status === 502 && raro.raw.indexOf('estructura-rara') === -1, raro.status + ' ' + raro.raw);

  /* Timeout */
  P.setMode('timeout');
  var t0 = Date.now();
  var lento = await post({ password: 'clave-e2e-2026' });
  var transcurrido = Date.now() - t0;
  check('Timeout -> 504 con mensaje claro', lento.status === 504 && /tard\u00f3 demasiado/.test(lento.body.error), lento.status + ' ' + lento.raw);
  check('El timeout respeta el limite de 12s', transcurrido >= 11000 && transcurrido < 20000, transcurrido + 'ms');
  P.setMode('fixture');

  /* Configuracion incompleta */
  var pwdGuardado = window.process.env.PANEL_PASSWORD;
  P.setEnv({ PANEL_PASSWORD: null });
  var sinClave = await post({ password: 'cualquiera' });
  check('Sin PANEL_PASSWORD -> 500 de configuracion sin filtrar la variable', sinClave.status === 500 && sinClave.raw.indexOf('PANEL_PASSWORD') === -1 && /no est\u00e1 configurado correctamente/.test(sinClave.body.error), sinClave.status + ' ' + sinClave.raw);
  P.setEnv({ PANEL_PASSWORD: pwdGuardado });

  var urlGuardada = window.process.env.SUPABASE_URL;
  P.setEnv({ SUPABASE_URL: null });
  var sinUrl = await post({ password: 'clave-e2e-2026' });
  check('Sin SUPABASE_URL -> 500 de configuracion', sinUrl.status === 500 && /no est\u00e1 configurado correctamente/.test(sinUrl.body.error), sinUrl.status + ' ' + sinUrl.raw);
  P.setEnv({ SUPABASE_URL: urlGuardada });

  var keyGuardada = window.process.env.SUPABASE_SERVICE_ROLE_KEY;
  P.setEnv({ SUPABASE_SERVICE_ROLE_KEY: null });
  var sinKey = await post({ password: 'clave-e2e-2026' });
  check('Sin SUPABASE_SERVICE_ROLE_KEY -> 500 de configuracion', sinKey.status === 500 && sinKey.raw.indexOf('SUPABASE_SERVICE_ROLE_KEY') === -1, sinKey.status + ' ' + sinKey.raw);
  P.setEnv({ SUPABASE_SERVICE_ROLE_KEY: keyGuardada });

  /* Red real contra el proyecto Supabase (anon key: RLS oculta las filas) */
  P.setMode('real');
  P.setEnv({ SUPABASE_SERVICE_ROLE_KEY: __ANON_KEY__ });
  var red = await post({ password: 'clave-e2e-2026' });
  check('Consulta real a Supabase: 200 y arreglo', red.status === 200 && Array.isArray(red.body.data), red.status + ' ' + red.raw.slice(0, 120) + ' | clave usada: ' + String(window.process.env.SUPABASE_SERVICE_ROLE_KEY).slice(0, 26) + ' | url: ' + String(P.supabaseCalls[P.supabaseCalls.length - 1].url).slice(0, 90));
  P.setEnv({ SUPABASE_SERVICE_ROLE_KEY: keyGuardada });
  P.setMode('fixture');
  return checks;
};
"""

# ---------------------------------------------------------------- harness


def build_harness():
    shim = (
        JS_SHIM
        .replace("__FIXTURE__", json.dumps(FIXTURE, ensure_ascii=False))
        .replace("__PASSWORD__", json.dumps(PASSWORD))
        .replace("__SUPABASE_URL__", json.dumps(SUPABASE_URL))
        .replace("__SERVICE_KEY__", json.dumps(SERVICE_KEY_DUMMY))
    )
    unit = JS_UNIT_TESTS.replace("__ANON_KEY__", json.dumps(ANON_KEY))
    bloques = [
        "<script>\n" + shim + "\n</script>",
        "<script>\n" + FN_SRC + "\n</script>",
        "<script>\nwindow.__panel.handler = window.exports.handler;\n</script>",
        "<script>\n" + JS_UI_TESTS_A + unit + "\n</script>",
    ]
    marcador = "  <!-- Lógica del panel."
    assert marcador in PANEL_HTML, "no se encontro el marcador para inyectar el harness"
    return PANEL_HTML.replace(marcador, "\n".join(bloques) + "\n" + marcador, 1)


EXPECTED_CSV_HEADER = '"Nombre";"Celular";"Comuna";"Referido por";"Le gusta";"Problema principal";"Seguridad nocturna";"Propuesta";"Quiere contacto";"Fecha"'


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    puerto = sock.getsockname()[1]
    sock.close()
    return puerto


def start_server():
    puerto = free_port()
    harness = build_harness()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/_panel_e2e.html"):
                cuerpo = harness.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(cuerpo)
                return
            super().do_GET()

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", puerto),
        lambda *a, **k: Handler(*a, directory=str(ROOT), **k),
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, puerto


class CDP:
    """Cliente minimo de Chrome DevTools Protocol sobre websockets."""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._pending = {}
        self.events = []

    async def start(self):
        self._task = asyncio.create_task(self._reader())

    async def _reader(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                else:
                    self.events.append(msg)
        except Exception:
            pass

    async def send(self, method, params=None, timeout=90):
        self._id += 1
        mid = self._id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        msg = await asyncio.wait_for(fut, timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method} -> {msg['error']}")
        return msg.get("result", {})

    async def evaluate(self, expression, await_promise=False, timeout=180):
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "timeout": timeout * 1000,
            },
            timeout=timeout + 30,
        )
        if "exceptionDetails" in res:
            raise RuntimeError("Excepcion en la pagina: " + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:800])
        return res.get("result", {}).get("value")


CHROME = next((c for c in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"),
] if Path(c).exists()), "")


def esperar_json(url, timeout=40):
    inicio = time.time()
    ultimo = None
    while time.time() - inicio < timeout:
        try:
            return requests.get(url, timeout=2).json()
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            time.sleep(0.3)
    raise RuntimeError("Chrome no respondio en " + url + ": " + str(ultimo))


def errores_consola(events):
    salida = []
    for ev in events:
        metodo = ev.get("method")
        if metodo == "Runtime.exceptionThrown":
            salida.append("excepcion: " + json.dumps(ev["params"]["exceptionDetails"], ensure_ascii=False)[:300])
        elif metodo == "Runtime.consoleAPICalled" and ev["params"].get("type") == "error":
            textos = [str(arg.get("value", arg.get("description", ""))) for arg in ev["params"].get("args", [])]
            salida.append("console.error: " + " | ".join(textos)[:300])
        elif metodo == "Log.entryAdded":
            entry = ev["params"]["entry"]
            texto_entry = str(entry.get("text", "")) + " " + str(entry.get("url", ""))
            if entry.get("level") == "error" and "favicon" not in texto_entry:
                salida.append("log.error: " + str(entry.get("text"))[:300])
    return salida


def verificar_csv():
    resultados = []
    archivos = sorted(DOWNLOAD_DIR.glob("*.csv"))
    if not archivos:
        return [("Descarga real del CSV al disco", False, "no se encontro ningun .csv en " + str(DOWNLOAD_DIR))]
    ruta = archivos[0]
    datos = ruta.read_bytes()
    resultados.append(("Descarga real del archivo CSV al disco", True, ruta.name + " (" + str(len(datos)) + " bytes)"))
    resultados.append(("CSV con BOM UTF-8", datos.startswith(b"\xef\xbb\xbf"), "primeros bytes: " + datos[:3].hex()))
    filas = list(csv.reader(io.StringIO(datos.decode("utf-8-sig")), delimiter=";"))
    encabezado = next(csv.reader(io.StringIO(EXPECTED_CSV_HEADER), delimiter=";"))
    resultados.append(("CSV: encabezado con las 10 columnas", filas[0] == encabezado, " | ".join(filas[0])))
    resultados.append(("CSV: 5 filas (encabezado + 4 respuestas)", len(filas) == 5, str(len(filas)) + " filas"))
    if len(filas) == 5:
        fila1 = ["Ana Gómez Restrepo", "3001234567", "Belen", "Ana Gómez", "Seguridad", "Movilidad/trafico", "Poco seguro/a", "Más cámaras de seguridad en los parques", "Si"]
        resultados.append(("CSV: fila 1 completa y con acentos", filas[1][:9] == fila1, " | ".join(filas[1])))
        resultados.append(("CSV: comillas dobles y ; bien escapados", filas[3][7] == 'Poner "comillas" y ; punto y coma\ncon salto', repr(filas[3][7])))
        resultados.append(("CSV: fila sin datos usa 'Sin dato'", filas[4][1:9] == ["Sin dato"] * 8, " | ".join(filas[4])))
        resultados.append(("CSV: fecha legible dd/mm/aaaa", bool(re.match(r"^\d{2}/\d{2}/2026", filas[1][9])), filas[1][9]))
    return resultados


async def esperar_pagina(page, timeout=60):
    inicio = time.time()
    intentos = 0
    while time.time() - inicio < timeout:
        estado = await page.evaluate("(function(){return {listo: !!(window.__panel && window.__panel.handler), panel: typeof window.__panel, exp: typeof window.exports, runUi: typeof window.__runUiTests, chart: typeof Chart, ready: document.readyState, scripts: document.querySelectorAll('script').length};})()")
        intentos += 1
        if intentos % 10 == 1:
            print("   [espera %d] %s" % (intentos, json.dumps(estado, ensure_ascii=False)), flush=True)
        if estado and estado.get("listo") and estado.get("chart") != "undefined":
            return True
        if intentos > 25:
            for linea in errores_consola(page.events):
                print("   [consola] " + linea[:400], flush=True)
            break
        await asyncio.sleep(0.4)
    return False


async def ejecutar():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    for viejo in DOWNLOAD_DIR.glob("*"):
        viejo.unlink()
    httpd, puerto = start_server()
    chrome_port = free_port()
    perfil = ROOT / "_e2e_chrome_profile"
    shutil.rmtree(perfil, ignore_errors=True)
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--remote-debugging-port=" + str(chrome_port),
         "--user-data-dir=" + str(perfil), "--no-first-run", "--no-default-browser-check",
         "--disable-extensions", "--disable-gpu", "--hide-scrollbars",
         "--window-size=1280,900", "--lang=es-CO", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ui, unit, csv_res, eventos, eventos_ui = [], [], [], [], 0
    try:
        version = esperar_json("http://127.0.0.1:" + str(chrome_port) + "/json/version")
        objetivos = esperar_json("http://127.0.0.1:" + str(chrome_port) + "/json/list")
        objetivo = next(o for o in objetivos if o.get("type") == "page")
        async with websockets.connect(version["webSocketDebuggerUrl"], max_size=None) as bws:
            navegador = CDP(bws)
            await navegador.start()
            await navegador.send("Browser.setDownloadBehavior", {
                "behavior": "allow", "downloadPath": str(DOWNLOAD_DIR), "eventsEnabled": True})
            async with websockets.connect(objetivo["webSocketDebuggerUrl"], max_size=None) as pws:
                page = CDP(pws)
                await page.start()
                for comando in ("Page.enable", "Runtime.enable", "Log.enable"):
                    await page.send(comando)
                await page.send("Page.navigate", {"url": "http://127.0.0.1:" + str(puerto) + "/_panel_e2e.html"})
                if not await esperar_pagina(page):
                    raise RuntimeError("La pagina del panel no termino de cargar (Chart.js o el harness no respondieron)")
                print(">> Panel cargado. Pruebas de interfaz (login, graficas, tabla, CSV)...")
                ui = await page.evaluate("window.__runUiTests()", await_promise=True)
                eventos_ui = len(page.events)
                print(">> Pruebas de la funcion en el navegador (incluye una llamada real a Supabase)...")
                unit = await page.evaluate("window.__runUnitTests()", await_promise=True)
                await asyncio.sleep(2.5)
                csv_res = verificar_csv()
                eventos = page.events
    finally:
        chrome.terminate()
        httpd.shutdown()

    todos = ([("INTERFAZ | " + c["name"], c["ok"], c["detail"]) for c in (ui or [])]
             + [("FUNCION  | " + c["name"], c["ok"], c["detail"]) for c in (unit or [])]
             + csv_res)
    errores_ui = errores_consola(eventos[:eventos_ui])
    print("\n=================== RESULTADOS ===================")
    fallos = 0
    for nombre, ok, detalle in todos:
        if not ok:
            fallos += 1
        print("[" + ("OK   " if ok else "FALLO") + "] " + nombre + ("   -> " + detalle if detalle else ""))
    print("==================================================")
    print("Comprobaciones: " + str(len(todos)) + " | Fallos: " + str(fallos))
    print("Errores de consola durante el uso normal del panel: " + str(len(errores_ui)))
    for linea in errores_ui:
        print("   " + linea)
    print("Logs de error del servidor (esperados en las pruebas de error): " + str(len(errores_consola(eventos))))
    for linea in errores_consola(eventos):
        print("   " + linea)
    return 0 if (fallos == 0 and not errores_ui) else 1


if __name__ == "__main__":
    if not CHROME:
        raise SystemExit("No se encontro chrome.exe")
    sys.exit(asyncio.run(ejecutar()))
