'use strict';

/**
 * ============================================================
 * CAMPAÑA SEBAS LÓPEZ - ALCALDÍA DE MEDELLÍN
 * Netlify Function: PANEL PRIVADO DE RESPUESTAS
 * Endpoint: POST /.netlify/functions/panel-data
 * ------------------------------------------------------------
 * 1. Valida la contraseña compartida del equipo contra la variable
 *    de entorno PANEL_PASSWORD (nunca en el navegador).
 * 2. Si coincide, lee TODAS las filas de la tabla "respuestas" en
 *    Supabase usando SUPABASE_SERVICE_ROLE_KEY (ignora RLS porque
 *    la tabla solo tiene política de INSERT para el rol anon).
 * 3. Devuelve { data: [...] } (200) o un mensaje claro de error
 *    sin exponer credenciales ni detalles internos.
 *
 * Variables de entorno requeridas (se configuran en Netlify):
 *   - PANEL_PASSWORD
 *   - SUPABASE_URL
 *   - SUPABASE_SERVICE_ROLE_KEY
 * ============================================================
 */

const crypto = require('crypto');

// --- Configuración ---
const SUPABASE_TABLE = 'respuestas';
const SUPABASE_COLUMNS = 'id,created_at,nombre,celular,respuestas';
const SUPABASE_ORDER = 'created_at.desc';
const REQUEST_TIMEOUT_MS = 12000;
const ESPERA_FALLO_MS = 400; // retardo ante contraseña incorrecta (frena fuerza bruta)

const MENSAJE_CONTRASENA = 'Contraseña incorrecta';
const MENSAJE_TEMPORAL = 'No se pudieron obtener las respuestas en este momento. Intenta de nuevo en unos minutos.';
const MENSAJE_TIMEOUT = 'La consulta tardó demasiado. Intenta de nuevo en unos segundos.';
const MENSAJE_CONFIG = 'El panel no está configurado correctamente. Contacta al administrador.';

const HEADERS_JSON = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store, no-cache, must-revalidate, private',
  'X-Content-Type-Options': 'nosniff'
};

/**
 * Respuesta JSON uniforme para Netlify Functions.
 * @param {number} statusCode
 * @param {object} cuerpo
 * @returns {{statusCode: number, headers: object, body: string}}
 */
function respuesta(statusCode, cuerpo) {
  return { statusCode: statusCode, headers: HEADERS_JSON, body: JSON.stringify(cuerpo) };
}

/**
 * Comparación de strings en tiempo constante (evita ataques de temporización).
 * @param {string} a
 * @param {string} b
 * @returns {boolean}
 */
function coinciden(a, b) {
  const bufferA = Buffer.from(String(a), 'utf8');
  const bufferB = Buffer.from(String(b), 'utf8');
  const largo = Math.max(bufferA.length, bufferB.length, 1);
  const rellenoA = Buffer.alloc(largo);
  const rellenoB = Buffer.alloc(largo);
  bufferA.copy(rellenoA);
  bufferB.copy(rellenoB);
  const iguales = crypto.timingSafeEqual(rellenoA, rellenoB);
  return iguales && bufferA.length === bufferB.length;
}

/**
 * Lee el body del evento como objeto JSON.
 * @param {object} event
 * @returns {object|null} null si el body no existe o no es JSON válido
 */
function leerCuerpo(event) {
  let raw = (event && typeof event.body === 'string') ? event.body : '';
  if (raw === '' && event && typeof event.body === 'object' && event.body !== null) {
    return event.body; // Netlify puede entregar el body ya parseado en algunos casos
  }
  if (event && event.isBase64Encoded && raw !== '') {
    raw = Buffer.from(raw, 'base64').toString('utf8');
  }
  if (typeof raw !== 'string' || raw.trim() === '') return null;
  try {
    const parsed = JSON.parse(raw);
    // El body debe ser un objeto JSON con la contraseña (no un arreglo ni un escalar)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed;
  } catch (err) {
    return null;
  }
}

/**
 * Consulta Supabase (REST API / PostgREST) con la service_role key.
 * @returns {Promise<{ok: boolean, filas?: Array, status?: number, mensaje?: string}>}
 */
async function consultarRespuestas() {
  const urlBase = String(process.env.SUPABASE_URL || '').replace(/\/+$/, '');
  const serviceKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || '');

  const params = new URLSearchParams();
  params.set('select', SUPABASE_COLUMNS);
  params.set('order', SUPABASE_ORDER);
  const endpoint = urlBase + '/rest/v1/' + SUPABASE_TABLE + '?' + params.toString();

  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(endpoint, {
      method: 'GET',
      headers: {
        apikey: serviceKey,
        Authorization: 'Bearer ' + serviceKey,
        Accept: 'application/json'
      },
      signal: controller.signal
    });

    if (!res.ok) {
      // El detalle queda SOLO en los logs del servidor
      const detalle = await res.text().catch(function () { return ''; });
      console.error('[panel-data] Supabase respondió con estado ' + res.status + ':', String(detalle).slice(0, 300));
      return { ok: false, status: 502, mensaje: MENSAJE_TEMPORAL };
    }

    const filas = await res.json().catch(function () { return null; });
    if (!Array.isArray(filas)) {
      console.error('[panel-data] Supabase devolvió una estructura inesperada (se esperaba un arreglo).');
      return { ok: false, status: 502, mensaje: MENSAJE_TEMPORAL };
    }

    return { ok: true, filas: filas };
  } catch (err) {
    const abortado = !!err && (err.name === 'AbortError' || err.code === 'ABORT_ERR');
    console.error('[panel-data] Error consultando Supabase:', abortado ? 'tiempo de espera agotado' : (err && err.message));
    return {
      ok: false,
      status: abortado ? 504 : 502,
      mensaje: abortado ? MENSAJE_TIMEOUT : MENSAJE_TEMPORAL
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Handler principal de la Netlify Function.
 */
exports.handler = async function (event) {
  // 1. Solo POST
  if (!event || event.httpMethod !== 'POST') {
    return respuesta(405, { error: 'Método no permitido' });
  }

  // 2. Verificar que el panel esté configurado
  const passwordEsperado = String(process.env.PANEL_PASSWORD || '');
  if (passwordEsperado === '') {
    console.error('[panel-data] Falta la variable de entorno PANEL_PASSWORD.');
    return respuesta(500, { error: MENSAJE_CONFIG });
  }

  // 3. Validar el body
  const cuerpo = leerCuerpo(event);
  if (cuerpo === null) {
    return respuesta(400, { error: 'Solicitud inválida' });
  }

  // 4. Validar la contraseña
  const passwordRecibido = typeof cuerpo.password === 'string' ? cuerpo.password : '';
  if (passwordRecibido === '' || !coinciden(passwordRecibido, passwordEsperado)) {
    await new Promise(function (resolve) { setTimeout(resolve, ESPERA_FALLO_MS); });
    return respuesta(401, { error: MENSAJE_CONTRASENA });
  }

  // 5. Verificar credenciales de Supabase y el runtime
  const urlBase = String(process.env.SUPABASE_URL || '').trim();
  const serviceKey = String(process.env.SUPABASE_SERVICE_ROLE_KEY || '').trim();
  if (urlBase === '' || serviceKey === '') {
    console.error('[panel-data] Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY.');
    return respuesta(500, { error: MENSAJE_CONFIG });
  }
  if (typeof fetch !== 'function') {
    console.error('[panel-data] El runtime no incluye fetch nativo (se requiere Node >= 18).');
    return respuesta(500, { error: MENSAJE_CONFIG });
  }

  // 6. Traer todas las respuestas (orden: más recientes primero)
  const resultado = await consultarRespuestas();
  if (!resultado.ok) {
    return respuesta(resultado.status, { error: resultado.mensaje });
  }

  return respuesta(200, { data: resultado.filas });
};
