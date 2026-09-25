/**
 * ============================================================
 * CAMPAÑA SEBAS LÓPEZ - ALCALDÍA DE MEDELLÍN
 * Script principal: Inicialización de Supabase y Control de Formulario
 * ============================================================
 */

// 1. Configuración de credenciales de Supabase
const SUPABASE_CONFIG = {
  url: 'https://xndkpvsnlmyunlnqkrwf.supabase.co',
  anonKey: 'sb_publishable_a3dXjRpitFszJWvJgM-yvw_gvfszpS4',
  table: 'respuestas'
};

// Cliente de Supabase inicializado
let supabaseClient = null;

/**
 * Inicialización al cargar el DOM
 */
document.addEventListener('DOMContentLoaded', () => {
  initSupabase();
  initWelcomeScreen();
  initResetViewButton();

  initInteractiveForm();

});

/**
 * 1. Inicializar cliente de Supabase usando el SDK cargado vía CDN
 */
function initSupabase() {
  if (typeof window.supabase !== 'undefined' && typeof window.supabase.createClient === 'function') {
    try {
      supabaseClient = window.supabase.createClient(SUPABASE_CONFIG.url, SUPABASE_CONFIG.anonKey);
      console.log('✔ Supabase inicializado correctamente.');
    } catch (err) {
      console.error('Error al instanciar el cliente de Supabase:', err);
    }
  } else {
    console.warn('El SDK de Supabase aún no está disponible en window.supabase.');
  }
}

/**
 * 2. Función genérica para enviar respuestas a la tabla "respuestas"
 * 
 * Columnas de la tabla:
 * - id: uuid (auto)
 * - created_at: timestamptz (auto)
 * - nombre: text
 * - celular: text
 * - respuestas: jsonb
 *
 * @param {string} nombre
 * @param {string} celular
 * @param {object} respuestasObjeto
 * @returns {Promise<{success: boolean, data?: any, error?: any}>} En éxito, data es null
 *          porque la fila NO se solicita de vuelta (sin .select()).
 */
async function enviarFormulario(nombre, celular, respuestasObjeto) {
  // Asegurar que el cliente esté inicializado
  if (!supabaseClient) {
    initSupabase();
    if (!supabaseClient) {
      const errorMsg = 'No se pudo conectar con el servicio de base de datos. Por favor recarga la página.';
      mostrarErrorUI(errorMsg);
      return { success: false, error: new Error(errorMsg) };
    }
  }

  // Estructura del registro para la tabla 'respuestas'
  const payload = {
    nombre: (nombre || '').trim(),
    celular: (celular || '').trim(),
    respuestas: respuestasObjeto && typeof respuestasObjeto === 'object' ? respuestasObjeto : {}
  };

  try {
    // IMPORTANTE: NO encadenar .select() después de .insert().
    // La tabla "respuestas" tiene RLS con política de INSERT para el rol anon pero SIN
    // política de SELECT (para que nadie pueda leer las respuestas de otros usuarios).
    // Pedir de vuelta la fila insertada (Prefer: return=representation) hace que Postgres
    // exija privilegio de SELECT sobre la fila nueva y devuelva el error 42501.
    const { error } = await supabaseClient
      .from(SUPABASE_CONFIG.table)
      .insert(payload);

    if (error) {
      console.error('❌ Error devuelto por Supabase al insertar:', error);

      let mensajeUsuario = 'Tuvimos un inconveniente al guardar tus respuestas. Por favor inténtalo de nuevo.';

      // Diagnóstico amigable si falta la política RLS de INSERT
      if (error.code === '42501' || (error.message && error.message.includes('row-level security'))) {
        mensajeUsuario = 'Conexión a Supabase lograda, pero la tabla "respuestas" rechazó la escritura por políticas RLS (se requiere una política INSERT para el rol "anon"). Revisa la consola o las notas de configuración.';
      }

      mostrarErrorUI(mensajeUsuario, error);
      return { success: false, error };
    }

    // Éxito en la inserción: como no pedimos la fila de vuelta, el éxito se determina
    // únicamente por la ausencia de error (error === null).
    console.log('✔ Respuestas registradas en Supabase exitosamente.');
    ocultarErrorUI();
    mostrarPantallaExito(payload);
    return { success: true, data: null };

  } catch (err) {
    console.error('❌ Excepción de red o ejecución al enviar:', err);
    const mensajeRed = 'No fue posible conectar con el servidor. Revisa tu conexión a internet e inténtalo nuevamente.';
    mostrarErrorUI(mensajeRed, err);
    return { success: false, error: err };
  }
}


/**
 * 3. Manejo de Errores en la interfaz de usuario
 */
function mostrarErrorUI(mensaje, detalleError) {
  // Intentar mostrar en el contenedor del formulario si está visible, o en el general
  const formSection = document.getElementById('form-section');
  const targetId = (formSection && formSection.style.display !== 'none') ? 'form-alert-container' : 'alert-container';
  const alertContainer = document.getElementById(targetId) || document.getElementById('alert-container');
  if (!alertContainer) return;

  alertContainer.innerHTML = `
    <div class="alert-banner alert-error" role="alert">
      <svg fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
      </svg>
      <div class="alert-content">
        <div class="alert-title">Atención</div>
        <div>${escapeHtml(mensaje)}</div>
      </div>
      <button type="button" class="alert-close" onclick="ocultarErrorUI()" aria-label="Cerrar aviso">&times;</button>
    </div>
  `;
}

function ocultarErrorUI() {
  const alertContainers = [document.getElementById('alert-container'), document.getElementById('form-alert-container')];
  alertContainers.forEach(container => {
    if (container) container.innerHTML = '';
  });
}




/**
 * 4. Manejo de Éxito: Mostrar pantalla de agradecimiento
 */
function mostrarPantallaExito(datosEnviados) {
  const welcomeSection = document.getElementById('welcome-section');
  const successScreen = document.getElementById('success-screen');
  const detailsBox = document.getElementById('success-details-box');

  if (welcomeSection) {
    welcomeSection.style.display = 'none';
    welcomeSection.setAttribute('aria-hidden', 'true');
  }

  if (detailsBox && datosEnviados) {
    const totalRespuestas = datosEnviados.respuestas ? Object.keys(datosEnviados.respuestas).length : 0;
    detailsBox.innerHTML = `
      <p><span class="label">Participante:</span> <span class="val">${escapeHtml(datosEnviados.nombre || 'Anónimo')}</span></p>
      <p><span class="label">Contacto:</span> <span class="val">${escapeHtml(datosEnviados.celular || 'No especificado')}</span></p>
      <p><span class="label">Respuestas registradas:</span> <span class="val">${totalRespuestas} tema(s)</span></p>
    `;
  }

  if (successScreen) {
    successScreen.style.display = 'flex';
    successScreen.setAttribute('aria-hidden', 'false');
    successScreen.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

/**
 * Botón para restablecer la vista (útil en pruebas)
 */
function initResetViewButton() {
  const btnReset = document.getElementById('btn-reset-view');
  if (!btnReset) return;

  btnReset.addEventListener('click', () => {
    const formSection = document.getElementById('form-section');
    if (formSection) formSection.style.display = 'none';
    formAnswers = {};
    currentQuestionIndex = 0;

    const welcomeSection = document.getElementById('welcome-section');
    const successScreen = document.getElementById('success-screen');

    if (successScreen) successScreen.style.display = 'none';
    if (welcomeSection) {
      welcomeSection.style.display = 'flex';
      welcomeSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    ocultarErrorUI();
  });
}

/**
 * ============================================================
 * FORMULARIO INTERACTIVO PASO A PASO (TYPEFORM STYLE)
 * ============================================================
 */

// Definición de las 8 preguntas del formulario
const FORM_QUESTIONS = [
  // DATOS DEL CIUDADANO
  {
    id: 'nombre',
    block: 'bloque-datos',
    blockTitle: 'Tus datos',
    title: '¿Cómo te llamas?',
    helper: 'Escribe tu nombre completo para saber con quién conversamos.',
    type: 'text',
    placeholder: 'Ej. Juan Camilo López',
    required: true,
    key: 'nombre' // Va a columna nombre
  },
  {
    id: 'celular',
    block: 'bloque-datos',
    blockTitle: 'Tus datos',
    title: '¿Cuál es tu número de celular?',
    helper: 'Número de 10 dígitos (ej. 300 123 4567) para mantener el contacto.',
    type: 'tel',
    placeholder: '3001234567',
    required: true,
    key: 'celular' // Va a columna celular
  },
  {
    id: 'comuna',
    block: 'bloque-datos',
    blockTitle: 'Tus datos',
    title: '¿En qué comuna o corregimiento vives?',
    helper: 'Selecciona la zona de Medellín a la que perteneces.',
    type: 'select',
    required: true,
    key: 'comuna',
    options: [
      'Popular',
      'Santa Cruz',
      'Manrique',
      'Aranjuez',
      'Castilla',
      'Doce de Octubre',
      'Robledo',
      'Villa Hermosa',
      'Buenos Aires',
      'La Candelaria',
      'Laureles-Estadio',
      'La América',
      'San Javier',
      'El Poblado',
      'Guayabal',
      'Belén',
      'Corregimiento'
    ]
  },
  // BLOQUE "LO QUE TE GUSTA"
  {
    id: 'le_gusta',
    block: 'bloque-gusta',
    blockTitle: 'Lo que te gusta',
    title: '¿Qué es lo que más te gusta de tu barrio o comuna?',
    helper: 'Elige la opción que mejor represente lo positivo de tu entorno.',
    type: 'choice',
    required: true,
    key: 'le_gusta',
    options: [
      'Seguridad',
      'Movilidad/transporte',
      'Espacios públicos y parques',
      'Cultura y eventos',
      'Oportunidades de empleo',
      'Educación',
      'Otro'
    ]
  },
  // BLOQUE "LO QUE TE PREOCUPA"
  {
    id: 'problema_principal',
    block: 'bloque-preocupa',
    blockTitle: 'Lo que te preocupa',
    title: '¿Cuál es el principal problema que ves en Medellín hoy?',
    helper: 'Selecciona la prioridad más urgente que debe atenderse.',
    type: 'choice',
    required: true,
    key: 'problema_principal',
    options: [
      'Seguridad',
      'Movilidad/tráfico',
      'Empleo',
      'Salud',
      'Educación',
      'Espacio público / andenes',
      'Medio ambiente',
      'Corrupción',
      'Otro'
    ]
  },
  {
    id: 'seguridad_nocturna',
    block: 'bloque-preocupa',
    blockTitle: 'Lo que te preocupa',
    title: '¿Qué tan seguro/a te sientes caminando en tu barrio de noche?',
    helper: 'Responde con total sinceridad.',
    type: 'binary',
    required: true,
    key: 'seguridad_nocturna',
    options: ['Sí', 'No']
  },
  // BLOQUE "LO QUE PROPONES"
  {
    id: 'propuesta_cambio',
    block: 'bloque-propones',
    blockTitle: 'Lo que propones',
    title: 'Si pudieras cambiar una sola cosa en Medellín, ¿cuál sería?',
    helper: 'Escribe tu propuesta o idea principal (máximo 200 caracteres).',
    type: 'textarea',
    maxLength: 200,
    placeholder: 'Ej. Más cámaras y vigilancia en los parques de mi comuna...',
    required: true,
    key: 'propuesta_cambio'
  },
  {
    id: 'quiere_contacto',
    block: 'bloque-propones',
    blockTitle: 'Lo que propones',
    title: '¿Te gustaría que te contactemos con más información sobre las propuestas de la campaña?',
    helper: 'Mantente informado sobre las iniciativas ciudadanas de Sebas López.',
    type: 'binary',
    required: true,
    key: 'quiere_contacto',
    options: ['Sí', 'No']
  }
];

// Estado global de respuestas y navegación
let currentQuestionIndex = 0;
let formAnswers = {};
let navigationDirection = 'forward'; // 'forward' | 'backward'

/**
 * Inicialización del flujo interactivo del formulario
 */
function initInteractiveForm() {
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');

  if (btnPrev) {
    btnPrev.addEventListener('click', () => {
      if (currentQuestionIndex > 0) {
        navigationDirection = 'backward';
        currentQuestionIndex--;
        renderCurrentQuestion();
      }
    });
  }

  if (btnNext) {
    btnNext.addEventListener('click', handleNextOrSubmit);
  }
}

/**
 * Manejo de la acción Siguiente o Enviar
 */
async function handleNextOrSubmit() {
  const currentQ = FORM_QUESTIONS[currentQuestionIndex];
  if (!isCurrentQuestionValid()) {
    mostrarErrorUI('Por favor completa la respuesta antes de continuar.');
    return;
  }

  ocultarErrorUI();

  // Si no es la última pregunta, avanzar
  if (currentQuestionIndex < FORM_QUESTIONS.length - 1) {
    navigationDirection = 'forward';
    currentQuestionIndex++;
    renderCurrentQuestion();
  } else {
    // Es la última pregunta: Enviar a Supabase
    await submitFinalForm();
  }
}

/**
 * Envío final a Supabase usando enviarFormulario(nombre, celular, respuestasObjeto)
 */
async function submitFinalForm() {
  const btnNext = document.getElementById('btn-next');
  const btnNextText = document.getElementById('btn-next-text');
  const btnNextIcon = document.getElementById('btn-next-icon');
  const btnPrev = document.getElementById('btn-prev');

  // Preparar parámetros exactos solicitados
  const nombre = formAnswers.nombre || '';
  const celular = formAnswers.celular || '';

  const respuestasObjeto = {
    comuna: formAnswers.comuna || '',
    le_gusta: formAnswers.le_gusta || '',
    problema_principal: formAnswers.problema_principal || '',
    seguridad_nocturna: formAnswers.seguridad_nocturna || '',
    propuesta_cambio: formAnswers.propuesta_cambio || '',
    quiere_contacto: formAnswers.quiere_contacto || ''
  };

  // Estado de carga en el botón
  if (btnNext) btnNext.disabled = true;
  if (btnPrev) btnPrev.disabled = true;
  if (btnNextIcon) btnNextIcon.style.display = 'none';
  if (btnNextText) btnNextText.innerHTML = '<span class="btn-spinner"></span> Guardando...';

  try {
    const result = await enviarFormulario(nombre, celular, respuestasObjeto);
    if (!result.success) {
      // Si falla, se muestra el banner de error sin perder los datos
      if (btnNext) btnNext.disabled = false;
      if (btnPrev) btnPrev.disabled = false;
      if (btnNextIcon) btnNextIcon.style.display = 'inline-block';
      if (btnNextText) btnNextText.textContent = 'Enviar respuestas';
    } else {
      // Éxito: Ocultar sección de formulario
      const formSection = document.getElementById('form-section');
      if (formSection) formSection.style.display = 'none';
    }
  } catch (err) {
    console.error('Error durante el envío final:', err);
    if (btnNext) btnNext.disabled = false;
    if (btnPrev) btnPrev.disabled = false;
    if (btnNextIcon) btnNextIcon.style.display = 'inline-block';
    if (btnNextText) btnNextText.textContent = 'Enviar respuestas';
  }
}

/**
 * Renderizado de la pregunta actual según currentQuestionIndex
 */
function renderCurrentQuestion() {
  const container = document.getElementById('question-container');
  const stepText = document.getElementById('progress-step-text');
  const percentText = document.getElementById('progress-percent-text');
  const progressFill = document.getElementById('progress-fill');
  const progressTrack = document.getElementById('progress-track');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const btnNextText = document.getElementById('btn-next-text');
  const btnNextIcon = document.getElementById('btn-next-icon');

  if (!container) return;

  const total = FORM_QUESTIONS.length;
  const current = currentQuestionIndex;
  const q = FORM_QUESTIONS[current];

  // Actualizar barra de progreso
  const progressPercent = Math.round(((current + 1) / total) * 100);
  if (stepText) stepText.textContent = `Paso ${current + 1} de ${total}`;
  if (percentText) percentText.textContent = `${progressPercent}%`;
  if (progressFill) progressFill.style.width = `${progressPercent}%`;
  if (progressTrack) progressTrack.setAttribute('aria-valuenow', progressPercent);

  // Visibilidad del botón Atrás
  if (btnPrev) {
    btnPrev.style.visibility = current === 0 ? 'hidden' : 'visible';
    btnPrev.disabled = false;
  }

  // Texto e icono del botón Siguiente / Enviar
  const isLastQuestion = current === total - 1;
  if (btnNextText) {
    btnNextText.textContent = isLastQuestion ? 'Enviar respuestas' : 'Siguiente';
  }
  if (btnNextIcon) {
    btnNextIcon.style.display = 'inline-block';
    if (isLastQuestion) {
      btnNextIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />';
    } else {
      btnNextIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"></path>';
    }
  }

  // Clase de animación de transición (slide/fade)
  const animClass = navigationDirection === 'backward' ? 'slide-enter-backward' : 'slide-enter-forward';

  // Renderizar contenido según tipo de pregunta
  let inputHtml = getQuestionInputHtml(q);

  // Inyectar HTML con animación
  container.innerHTML = `
    <div class="question-step ${animClass}">
      <div class="block-header ${q.block}">
        <span>${escapeHtml(q.blockTitle)}</span>
      </div>
      <h2 class="question-title">${escapeHtml(q.title)}</h2>
      <p class="question-helper">${escapeHtml(q.helper)}</p>
      ${inputHtml}
    </div>
  `;

  // Asignar listeners según el tipo de pregunta
  attachQuestionListeners(q);

  // Actualizar estado del botón Siguiente
  updateNextButtonState();
}
/**
 * Genera el markup HTML para cada tipo de entrada
 */
function getQuestionInputHtml(q) {
  const currentVal = formAnswers[q.key] || '';

  if (q.type === 'text' || q.type === 'tel') {
    const isTel = q.type === 'tel';
    return `
      <input
        type="${isTel ? 'tel' : 'text'}"
        class="form-input-text"
        id="input-${q.id}"
        placeholder="${escapeHtml(q.placeholder || '')}"
        value="${escapeHtml(currentVal)}"
        autocomplete="${isTel ? 'tel' : 'name'}"
        maxlength="${isTel ? '10' : '80'}"
        inputmode="${isTel ? 'numeric' : 'text'}"
      />
    `;
  }

  if (q.type === 'select') {
    const optionsHtml = q.options.map(opt => {
      const isSelected = currentVal === opt ? 'selected' : '';
      return `<option value="${escapeHtml(opt)}" ${isSelected}>${escapeHtml(opt)}</option>`;
    }).join('');

    return `
      <div class="form-select-wrapper">
        <select class="form-select" id="input-${q.id}" aria-label="${escapeHtml(q.title)}">
          <option value="" disabled ${!currentVal ? 'selected' : ''}>Selecciona tu comuna o corregimiento...</option>
          ${optionsHtml}
        </select>
        <svg class="select-chevron" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </div>
    `;
  }

  if (q.type === 'choice') {
    const optionsHtml = q.options.map(opt => {
      const isSelected = currentVal === opt ? 'selected' : '';
      return `
        <button type="button" class="option-btn ${isSelected}" data-val="${escapeHtml(opt)}">
          <span>${escapeHtml(opt)}</span>
          <span class="option-indicator" aria-hidden="true"></span>
        </button>
      `;
    }).join('');

    return `<div class="options-grid" id="options-${q.id}">${optionsHtml}</div>`;
  }

  if (q.type === 'binary') {
    const yesSelected = currentVal === 'Sí' ? 'selected' : '';
    const noSelected = currentVal === 'No' ? 'selected' : '';

    return `
      <div class="binary-choice-group" id="binary-${q.id}">
        <button type="button" class="btn-binary ${yesSelected}" data-val="Sí">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <span>Sí</span>
        </button>
        <button type="button" class="btn-binary ${noSelected}" data-val="No">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span>No</span>
        </button>
      </div>
    `;
  }

  if (q.type === 'textarea') {
    const charCount = currentVal.length;
    return `
      <div class="textarea-wrapper">
        <textarea
          class="form-textarea"
          id="input-${q.id}"
          placeholder="${escapeHtml(q.placeholder || '')}"
          maxlength="${q.maxLength || 200}"
          rows="4"
        >${escapeHtml(currentVal)}</textarea>
        <div class="char-counter" id="char-counter">${charCount} / ${q.maxLength || 200}</div>
      </div>
    `;
  }

  return '';
}

/**
 * Validar si la pregunta actual tiene una respuesta válida
 */
function isCurrentQuestionValid() {
  const q = FORM_QUESTIONS[currentQuestionIndex];
  if (!q.required) return true;

  const val = (formAnswers[q.key] || '').toString().trim();

  if (q.type === 'tel') {
    // Celular colombiano: exactamente 10 dígitos numéricos
    const cleanNum = val.replace(/\D/g, '');
    return cleanNum.length === 10;
  }

  if (q.type === 'text' || q.type === 'textarea') {
    return val.length >= 2;
  }

  if (q.type === 'select' || q.type === 'choice' || q.type === 'binary') {
    return val.length > 0;
  }

  return false;
}

/**
 * Habilitar o deshabilitar el botón Siguiente según la validez actual
 */
function updateNextButtonState() {
  const btnNext = document.getElementById('btn-next');
  if (btnNext) {
    btnNext.disabled = !isCurrentQuestionValid();
  }
}

/**
 * Event listeners para los controles de la pregunta activa
 */
function attachQuestionListeners(q) {
  if (q.type === 'text') {
    const input = document.getElementById(`input-${q.id}`);
    if (input) {
      input.focus();
      input.addEventListener('input', (e) => {
        formAnswers[q.key] = e.target.value;
        updateNextButtonState();
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && isCurrentQuestionValid()) {
          e.preventDefault();
          handleNextOrSubmit();
        }
      });
    }
  } else if (q.type === 'tel') {
    const input = document.getElementById(`input-${q.id}`);
    if (input) {
      input.focus();
      input.addEventListener('input', (e) => {
        let clean = e.target.value.replace(/\D/g, '').slice(0, 10);
        e.target.value = clean;
        formAnswers[q.key] = clean;
        updateNextButtonState();
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && isCurrentQuestionValid()) {
          e.preventDefault();
          handleNextOrSubmit();
        }
      });
    }
  } else if (q.type === 'select') {
    const select = document.getElementById(`input-${q.id}`);
    if (select) {
      select.addEventListener('change', (e) => {
        formAnswers[q.key] = e.target.value;
        updateNextButtonState();
      });
    }
  } else if (q.type === 'choice') {
    const grid = document.getElementById(`options-${q.id}`);
    if (grid) {
      const buttons = grid.querySelectorAll('.option-btn');
      buttons.forEach(btn => {
        btn.addEventListener('click', () => {
          buttons.forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          formAnswers[q.key] = btn.getAttribute('data-val');
          updateNextButtonState();

          setTimeout(() => {
            if (isCurrentQuestionValid() && currentQuestionIndex < FORM_QUESTIONS.length - 1) {
              navigationDirection = 'forward';
              currentQuestionIndex++;
              renderCurrentQuestion();
            }
          }, 220);
        });
      });
    }
  } else if (q.type === 'binary') {
    const group = document.getElementById(`binary-${q.id}`);
    if (group) {
      const buttons = group.querySelectorAll('.btn-binary');
      buttons.forEach(btn => {
        btn.addEventListener('click', () => {
          buttons.forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          formAnswers[q.key] = btn.getAttribute('data-val');
          updateNextButtonState();

          setTimeout(() => {
            if (isCurrentQuestionValid()) {
              handleNextOrSubmit();
            }
          }, 220);
        });
      });
    }
  } else if (q.type === 'textarea') {
    const textarea = document.getElementById(`input-${q.id}`);
    const counter = document.getElementById('char-counter');
    if (textarea) {
      textarea.focus();
      textarea.addEventListener('input', (e) => {
        const val = e.target.value;
        formAnswers[q.key] = val;
        if (counter) {
          const max = q.maxLength || 200;
          counter.textContent = `${val.length} / ${max}`;
          counter.classList.toggle('limit-near', val.length >= max * 0.85);
          counter.classList.toggle('limit-reached', val.length >= max);
        }
        updateNextButtonState();
      });
    }
  }
}

/**
 * Transición desde la pantalla de bienvenida al formulario
 */
function initWelcomeScreen() {
  const startButton = document.getElementById('btn-start');
  const welcomeSection = document.getElementById('welcome-section');
  const formSection = document.getElementById('form-section');

  if (!startButton) return;

  startButton.addEventListener('click', (event) => {
    event.preventDefault();
    console.log('>>> [Comenzar presionado] Usuario inició el cuestionario.');

    if (welcomeSection) {
      welcomeSection.style.display = 'none';
      welcomeSection.setAttribute('aria-hidden', 'true');
    }

    if (formSection) {
      formSection.style.display = 'flex';
      formSection.setAttribute('aria-hidden', 'false');
      // Renderizar primera pregunta
      navigationDirection = 'forward';
      currentQuestionIndex = 0;
      renderCurrentQuestion();
      formSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
}

/**
 * Sanitización básica contra XSS en cadenas
 */
function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

