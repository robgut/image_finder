import streamlit as st
import os

def save_photo(upl_file):
    try:
        buff = upl_file.getbuffer()
        with open('01_' + upl_file.name, 'wb') as f:
            f.write(buff)
        return True
    except Exception as ex:
        return False


st.title('Aplikacja do przesyłania zdjęć')
st.write(f'cwd:{os.getcwd()}')
uploaded_file = st.file_uploader('Wybierz zdjęcie', type=['png', 'jpeg', 'jpg'], accept_multiple_files=False)

if uploaded_file is not None:
    if save_photo(uploaded_file):
        st.success("Plik został pomyślnie zapisany!")
    else:
        st.error('Nie udało się zapisać pliku...')
