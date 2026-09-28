"""English and Spanish, on the pages a cleaner or an applicant actually opens.

The texts have been translated for a while — a job offer, a claim link, a
reminder. The pages those texts link to were not, so somebody set to Spanish
got a message in Spanish, tapped it, and landed on an English page. That is
arguably worse than not translating the text, because it promises something
the next screen does not deliver.

## Why the Spanish is written here rather than fetched

`translate.py` exists and works, and it is the right tool for text somebody
typed — a checklist item, an entry note, a message. It is the wrong tool for
the furniture of a page:

  * It costs an API call before the page can render. A cleaner standing at a
    locked door at eight in the morning should not wait on OpenRouter.
  * It fails soft, which for a message is right and for a page is not: the
    button silently comes back in English and nobody is told why.
  * The same button comes back worded differently on different days.

So the labels, buttons and headings are written down. What the owner types is
translated on the fly, because nobody can write that in advance.

## The English is the key

    {{ t('Clock in') }}

rather than `t('clock_in')`. A missing translation returns the English, which
means a half-translated page is a page in two languages rather than a page of
`clock_in.button.label`. It also means the templates stay readable to somebody
who does not speak Spanish, and a new string is never a broken string.
"""
import os

SUPPORTED = ('en', 'es')
DEFAULT = 'en'

# The cookie is set when somebody uses the toggle. It only ever overrides for
# that browser -- the cleaner's own record is what everything else follows.
COOKIE = 'akye_lang'


ES = {
    # ── Shared ────────────────────────────────────────────────────────────
    'Loading…': 'Cargando…',
    'Something went wrong.': 'Algo salió mal.',
    'Please try again.': 'Por favor, inténtalo de nuevo.',
    'Continue': 'Continuar',
    'Back': 'Atrás',
    'Submit': 'Enviar',
    'Send': 'Enviar',
    'Save': 'Guardar',
    'Optional': 'Opcional',
    'Required': 'Obligatorio',
    'Yes': 'Sí',
    'No': 'No',
    'Today': 'Hoy',
    'Tomorrow': 'Mañana',
    'Date to be confirmed': 'Fecha por confirmar',
    'English': 'English',
    'Spanish': 'Español',

    # ── The cleaner's day ────────────────────────────────────────────────
    'My Day': 'Mi día',
    'Your schedule': 'Tu horario',
    'Hi': 'Hola',
    'job coming up': 'trabajo próximo',
    'jobs coming up': 'trabajos próximos',
    'Time TBD': 'Hora por confirmar',
    'YOU EARN': 'TÚ GANAS',
    'Getting in:': 'Cómo entrar:',
    'Navigate': 'Cómo llegar',
    'Checklist': 'Lista de tareas',
    'With': 'Con',
    'a teammate (still being assigned)': 'un compañero (aún por asignar)',
    "Can't make it? Release this job": '¿No puedes ir? Libera este trabajo',
    'No jobs scheduled right now.': 'No tienes trabajos programados ahora.',
    "Enjoy the break — we'll text you when a new job is assigned.":
        'Disfruta el descanso — te avisaremos por mensaje cuando haya trabajo.',
    'Cleaning guides': 'Guías de limpieza',
    'Clock in': 'Marcar entrada',
    'Clock out': 'Marcar salida',
    'Clock in again': 'Marcar entrada otra vez',
    'On the clock': 'En turno',
    'h logged': 'h registradas',

    # ── A job offered to the team ────────────────────────────────────────
    'New job available!': '¡Trabajo disponible!',
    'Team job available!': '¡Trabajo en equipo disponible!',
    'When': 'Cuándo',
    'Service': 'Servicio',
    'Area': 'Zona',
    "YOU'D EARN": 'GANARÍAS',
    'flat for the job': 'fijo por el trabajo',
    'Claim this job': 'Tomar este trabajo',
    'First to claim gets it.': 'El primero en tomarlo se lo queda.',
    'First': 'Los primeros',
    'to claim get the open spots.': 'en tomarlo se quedan los lugares libres.',
    "The full address appears once it's yours.":
        'La dirección completa aparece cuando sea tuyo.',
    'Claim my spot': 'Tomar mi lugar',
    'YOU WOULD EARN': 'GANARÍAS',
    'This job has been taken.': 'Este trabajo ya fue tomado.',
    "It's yours": 'Es tuyo',

    # ── Applying for a job ───────────────────────────────────────────────
    'Apply to join our team': 'Solicita unirte a nuestro equipo',
    'Your name': 'Tu nombre',
    'Full name': 'Nombre completo',
    'Email': 'Correo electrónico',
    'Phone': 'Teléfono',
    'Phone number': 'Número de teléfono',
    'City': 'Ciudad',
    'Zip code': 'Código postal',
    'Address': 'Dirección',
    'Experience': 'Experiencia',
    'Years of cleaning experience': 'Años de experiencia en limpieza',
    'Do you have your own transport?': '¿Tienes tu propio transporte?',
    'Are you legally allowed to work?': '¿Tienes permiso legal para trabajar?',
    'Tell us about yourself': 'Cuéntanos sobre ti',
    'Submit application': 'Enviar solicitud',
    'Thank you for applying': 'Gracias por tu solicitud',
    "We'll be in touch soon.": 'Nos pondremos en contacto pronto.',
    'This field is required.': 'Este campo es obligatorio.',
    'Please enter a valid email.': 'Por favor, introduce un correo válido.',

    # ── The interview ────────────────────────────────────────────────────
    'Your interview': 'Tu entrevista',
    'Question': 'Pregunta',
    'of': 'de',
    'Record your answer': 'Graba tu respuesta',
    'Type your answer': 'Escribe tu respuesta',
    'Start recording': 'Empezar a grabar',
    'Stop recording': 'Parar de grabar',
    'Next question': 'Siguiente pregunta',
    'Finish': 'Terminar',
    'Answer in English or Spanish — whichever you prefer.':
        'Responde en inglés o español — el que prefieras.',
    'Thank you — we have your answers.': 'Gracias — tenemos tus respuestas.',

    # ── Onboarding a new hire ────────────────────────────────────────────
    'Welcome': 'Bienvenida',
    'Getting you set up': 'Preparando todo',
    'Upload': 'Subir',
    'Sign': 'Firmar',
    'Signed': 'Firmado',
    'Done': 'Hecho',
    'Not done yet': 'Aún no',
    'Your agreement': 'Tu acuerdo',
    'I agree': 'Acepto',
}

TABLES = {'es': ES}


def normalise(lang):
    """'es-MX', 'ES', ' es ' -> 'es'. Anything unknown -> English."""
    code = (lang or '').strip().lower().replace('_', '-').split('-')[0]
    return code if code in SUPPORTED else DEFAULT


def t(text, lang=None):
    """The Spanish for this English, or the English if there is none.

    A missing entry is not an error and must never look like one. The page
    comes back in two languages, which is untidy and completely usable, rather
    than showing a key nobody can read.
    """
    if text is None:
        return ''
    code = normalise(lang if lang is not None else current())
    if code == DEFAULT:
        return text
    return TABLES.get(code, {}).get(text, text)


def current():
    """Which language this request is in.

    In order:
      1. `?lang=` in the address — how the toggle switches, and how a link can
         be sent in a particular language.
      2. The cookie that toggle set, so it sticks for that browser.
      3. The cleaner's own record, which is the setting the owner already
         keeps and which already decides what language their texts arrive in.
      4. English.
    """
    try:
        from flask import request, g, has_request_context
        if not has_request_context():
            return DEFAULT
        chosen = getattr(g, 'lang', None)
        if chosen:
            return chosen
        asked = request.args.get('lang')
        if asked:
            return normalise(asked)
        cookie = request.cookies.get(COOKIE)
        if cookie:
            return normalise(cookie)
        person = getattr(g, 'lang_person', None)
        if person is not None:
            return normalise(getattr(person, 'language', None))
    except Exception:
        pass
    return DEFAULT


def set_person(person):
    """Say whose language preference applies to this request.

    Called by the views that know who is looking -- the cleaner holding the
    token, the applicant part-way through an interview.
    """
    try:
        from flask import g
        g.lang_person = person
    except Exception:
        pass


def auto(text, lang=None):
    """Translate something the owner typed: a checklist item, an entry note.

    Nobody can write these in advance, so this is the one place the API is
    used on a page. It fails soft, returning the original -- which for
    somebody's own words is the right failure: an untranslated instruction is
    readable, and a missing one is not.
    """
    code = normalise(lang if lang is not None else current())
    if code == DEFAULT or not (text or '').strip():
        return text
    if not os.environ.get('OPENROUTER_API_KEY'):
        return text
    try:
        from translate import translate
        return translate(text, target=code) or text
    except Exception:
        return text


def install(app):
    """Make `t`, `auto` and `LANG` available in every template."""
    @app.context_processor
    def _inject():
        code = current()
        return {
            't': lambda s: t(s, code),
            'tr_auto': lambda s: auto(s, code),
            'LANG': code,
            'LANG_IS_ES': code == 'es',
        }
