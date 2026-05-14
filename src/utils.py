import os
import urllib.request
import streamlit as st

def ensure_database(db_path, download_url):
    """Ensure the SQLite DB exists, downloading it if necessary."""
    if not os.path.exists(db_path):
        try:
            urllib.request.urlretrieve(download_url, db_path)
        except Exception as e:
            st.error(f"Could not download database: {e}")
            return False
    return True
