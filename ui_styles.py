# ui_styles.py
import streamlit as st
import os

LOGO_PATH = "logo.png"  # place your logo.png in same folder

GLASS_CSS = """
:root{
  --accent:#6f8efb;
  --accent-2:#8ad4ff;
  --bg:#f6fbff;
  --muted:#7b8a99;
  --glass: rgba(255,255,255,0.65);
}
.center-card { max-width:900px; margin:28px auto; }
.glass-card {
  background: linear-gradient(180deg, rgba(255,255,255,0.60), rgba(255,255,255,0.50));
  border-radius:18px;
  padding:18px;
  box-shadow: 0 10px 30px rgba(16,24,40,0.06);
  border: 1px solid rgba(127,154,255,0.08);
  backdrop-filter: blur(8px);
}
.chat-user {
  background: rgba(42,203,155,0.12);
  color: #063a2b;
  padding: 12px;
  border-radius: 14px;
  margin-left: auto;
  margin-bottom: 10px;
  max-width: 78%;
}
.chat-bot {
  background: rgba(124,210,146,0.12);
  color: #083a1f;
  padding: 12px;
  border-radius: 14px;
  margin-right: auto;
  margin-bottom: 10px;
  max-width: 78%;
}
.center-card { text-align:center; }
.stButton>button { border-radius:10px; }
"""

def inject_style():
    st.markdown(f"<style>{GLASS_CSS}</style>", unsafe_allow_html=True)

def show_logo(width=200):
    try:
        st.image(LOGO_PATH, width=width)
    except Exception:
        st.markdown("<div style='font-weight:bold;font-size:20px;'>MedGuardian</div>", unsafe_allow_html=True)
