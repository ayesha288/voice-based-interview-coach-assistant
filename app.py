import streamlit as st
import random
import sqlite3
import uuid
import time
from datetime import datetime
from google import genai
from streamlit_mic_recorder import speech_to_text

# --- Database setup (matches official schema) ---
def init_db():
    conn = sqlite3.connect("interview_coach.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            session_id TEXT,
            learner_alias TEXT,
            question_id TEXT,
            question_text TEXT,
            transcript TEXT,
            filler_word_count INTEGER,
            star_structure_score INTEGER,
            learner_rating INTEGER,
            response_duration_sec REAL,
            retry_number INTEGER,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_response(row):
    conn = sqlite3.connect("interview_coach.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO responses
        (session_id, learner_alias, question_id, question_text, transcript,
         filler_word_count, star_structure_score, learner_rating,
         response_duration_sec, retry_number, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
    conn.commit()
    conn.close()

def get_alias_history(alias):
    conn = sqlite3.connect("interview_coach.db")
    c = conn.cursor()
    c.execute("""
        SELECT question_text, star_structure_score, filler_word_count, timestamp
        FROM responses WHERE learner_alias = ? ORDER BY timestamp DESC
    """, (alias,))
    rows = c.fetchall()
    conn.close()
    return rows

init_db()

# --- Question bank (question_id + text) ---
questions = {
    "NT-COACH-Q01": "Tell me about yourself.",
    "NT-COACH-Q02": "Why should we hire you?",
    "NT-COACH-Q03": "Describe a time you resolved a production incident.",
    "NT-COACH-Q04": "What are your strengths and weaknesses?",
    "NT-COACH-Q05": "Where do you see yourself in 5 years?",
}

filler_words = ["um", "uh", "like", "basically", "actually", "you know", "sort of", "kind of"]

def count_filler_words(text):
    text_lower = text.lower()
    return sum(text_lower.count(f) for f in filler_words)


star_signals = {
    "Situation": ["situation", "context", "when i", "at my", "during", "while working", "faced a", "there was"],
    "Task": ["task", "goal", "needed to", "had to", "responsible for", "my role", "objective"],
    "Action": ["i did", "i built", "i created", "i decided", "i implemented", "i approached", "i took", "i worked on", "so i"],
    "Result": ["result", "outcome", "as a result", "in the end", "successfully", "improved", "achieved", "learned", "led to"],
}

def score_star_structure(text):

    """Returns a score out of 4 (one point per STAR component detected) plus which components were found."""
    text_lower = text.lower()
    found = []
    for component, signals in star_signals.items():
        if any(signal in text_lower for signal in signals):
            found.append(component)
    return len(found), found
def generate_ai_feedback(question_text, star_score, star_found, filler_count):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

    missing_components = [c for c in ["Situation", "Task", "Action", "Result"] if c not in star_found]

    prompt = f"""You are a supportive interview coach. Based only on the metrics below (not the raw answer), write brief, encouraging, specific feedback in 3-4 sentences. Do not invent details about what the candidate said — only reference the metrics given.

Question asked: {question_text}
STAR structure score: {star_score}/4
STAR components detected: {', '.join(star_found) if star_found else 'None'}
STAR components missing: {', '.join(missing_components) if missing_components else 'None'}
Filler word count: {filler_count}

Write the feedback now."""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    return response.text

# --- Streamlit session state setup ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "retry_number" not in st.session_state:
    st.session_state.retry_number = {}
if "question_start_time" not in st.session_state:
    st.session_state.question_start_time = None

# --- UI ---
st.title("Voice-Based Interview Coaching Assistant")
st.warning(
    "⚠️ **This is a practice tool only.** Feedback is AI-generated and rule-based — it is "
    "**not** a hiring assessment and should never be used to make real hiring decisions. "
    "Please use an alias, not your real name."
)
learner_alias = st.text_input("Enter a learner alias (not your real name):", value=st.session_state.get("learner_alias", ""))
st.session_state.learner_alias = learner_alias

if not learner_alias:
    st.info("Please enter an alias above to begin practicing.")
else:
    tab1, tab2 = st.tabs(["Practice", "My History"])

    with tab1:
        if "current_qid" not in st.session_state:
            st.session_state.current_qid = random.choice(list(questions.keys()))
            st.session_state.question_start_time = time.time()

        qid = st.session_state.current_qid
        question_text = questions[qid]
        st.subheader(question_text)

        st.write("🎤 Click below to speak your answer, or type it in the box.")
        voice_text = speech_to_text(
            language='en',
            start_prompt="🎙️ Start Speaking",
            stop_prompt="⏹️ Stop",
            just_once=True,
            key='stt'
        )

        if voice_text:
            st.session_state.voice_answer = voice_text
            st.info("✏️ Please review the text below — speech recognition isn't perfect. Correct any mistakes before submitting.")

        answer = st.text_area(
            "Your answer (auto-filled from speech — please review and correct before submitting):",
            value=st.session_state.get("voice_answer", ""),
            height=150
        )

        if st.button("Submit Answer"):
            if answer.strip() == "":
                st.warning("Please type an answer before submitting.")
            else:
                duration = round(time.time() - st.session_state.question_start_time, 1)
                retry_num = st.session_state.retry_number.get(qid, 0) + 1
                st.session_state.retry_number[qid] = retry_num

                filler_count = count_filler_words(answer)

                # STAR score placeholder — we'll build this properly next step
                star_score, star_found = score_star_structure(answer)

                save_response((
                    st.session_state.session_id,
                    learner_alias,
                    qid,
                    question_text,
                    answer,
                    filler_count,
                    star_score,
                    None,  # learner_rating — added later via a rating widget
                    duration,
                    retry_num,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ))

                st.success(f"STAR score: {star_score}/4 | Filler words: {filler_count} | Time: {duration}s")

                with st.spinner("Generating personalized feedback..."):
                 ai_feedback = generate_ai_feedback(question_text, star_score, star_found, filler_count)

                st.subheader("Coach Feedback")
                st.write(ai_feedback)
                st.caption(
                    "ℹ️ This feedback is generated from rule-based metrics (STAR structure, filler word count) "
                    "and an AI language model. It may not capture every nuance of your answer — use it as "
                    "a guide, not a final judgment."
                )
        if st.button("Try a New Question"):
            st.session_state.current_qid = random.choice(list(questions.keys()))
            st.session_state.question_start_time = time.time()
            st.rerun()

    with tab2:
        st.subheader(f"History for: {learner_alias}")
        rows = get_alias_history(learner_alias)
        if not rows:
            st.write("No attempts yet.")
        else:
            for q, star, filler, t in rows:
                st.write(f"**{t}** — {q} — STAR: {star} | Fillers: {filler}")
                