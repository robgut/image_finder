import streamlit as st
import pandas as pd
from dotenv import dotenv_values
from dotenv import load_dotenv
from openai import OpenAI
from io import BytesIO
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Distance, VectorParams
import boto3
import base64


QDRANT_COLLECTION_NAME = "photo_collection"
EMBEDDING_DIM=3072
BUCKET_NAME = "nowy"

env = dotenv_values(".env")

@st.cache_resource
def get_qdrant_client():
    return QdrantClient(
        url="https://b5470214-616b-4989-b092-8f2ca4390bdf.eu-central-1-0.aws.cloud.qdrant.io:6333", 
        api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwiZXhwIjoxNzQ1OTI5NTQxfQ.gkg0uqTqL8pp2HFmd29AlayLkMxGynxcdwqv7CK3j1c",
    )

def get_openai_client():
    return OpenAI(api_key=st.session_state['openai_api_key'])
    # return OpenAI(api_key=env["OPENAI_API_KEY"])

def get_digital_ocean_client():
    return boto3.client('s3',)

def assure_qdrant_collection_exists():
    qdrant_client = get_qdrant_client()
    if not qdrant_client.collection_exists(QDRANT_COLLECTION_NAME):
        qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )

def get_embedding(openai_client, text, EMBEDDING_MODEL = "text-embedding-3-large", EMBEDDING_DIM = 3072):
    result = openai_client.embeddings.create(
        input=[text],
        model=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIM,
    )

    return result.data[0].embedding

def prepare_image_for_open_ai(image_bytes):
    image_data = base64.b64encode(image_bytes).decode('utf-8')

    return f"data:image/png;base64,{image_data}"

def get_text_from_image(openai_client, image_bytes):
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Stwórz opis obrazka, jakie widzisz tam elementy?"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": prepare_image_for_open_ai(image_bytes),
                            "detail": "high"
                        },
                    },
                ],
            }
        ],
    )

    return response.choices[0].message.content

def add_photo_to_qdrant(photo_dict: dict):
    qdrant_client = get_qdrant_client()
    points_count = qdrant_client.count(
        collection_name=QDRANT_COLLECTION_NAME,
        exact=True,
    )
    qdrant_client.upsert(
        collection_name=QDRANT_COLLECTION_NAME,
        points=[
            PointStruct(
                id=points_count.count + 1,
                vector=get_embedding(text=photo_dict['text'], openai_client=get_openai_client()),
                payload={
                    "text": photo_dict['text'],
                    'path':photo_dict['path'],
                },
            )
        ]
    )

def find_images(query=None):
    qdrant_client = get_qdrant_client()
    if not query:
        notes = qdrant_client.scroll(collection_name=QDRANT_COLLECTION_NAME, limit=10)[0]
        result = []
        for note in notes:
            result.append({
                "text": note.payload["text"],
                'path':note.payload['path'],
                "score": None,
            })

        return result

    else:
        notes = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=get_embedding(text=query, openai_client=get_openai_client()),
            limit=10,
        )
        result = []
        for note in notes:
            result.append({
                "text": note.payload["text"],
                "path":note.payload["path"],
                "score": note.score,
            })

        return result    

def save_image(img_bytes, img_name):
    try:
        s3 = get_digital_ocean_client()
        s3.upload_fileobj(img_bytes, BUCKET_NAME, Key=img_name)
        return True
    except Exception as ex:
        print(ex)
        return False
    
def get_image_list(keys:list = None):
    s3 = get_digital_ocean_client()
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix="img/")  
    if  keys != None:
        imgs = response['Contents']
        result = [{key:d[key] for key in keys} for d in imgs]  
        return result
    return response['Contents']

def image_already_saved(img_name):
    try:
        ret_val = False
        s3 = get_digital_ocean_client()

        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix="img/" + img_name)
        if 'Contents' not in response:
            return False
        
        for obj in response['Contents']:
            if img_name in obj['Key']:
                ret_val = True
                break
            
        return ret_val
    except Exception as ex:
        return True

def download_image(img_name):
    if image_already_saved(img_name):
        try:
            s3 = get_digital_ocean_client()
            image = BytesIO()

            data = s3.download_fileobj(BUCKET_NAME, "img/" + img_name, image)
            image.seek(0)

            return image.read()
        except:
            return None
    else:
        return None
    
def on_image_change(img_selected):
    if image_already_saved(img_selected):
        try:
            downloaded_img = download_image(img_selected)
            st.image(downloaded_img, 'Pobrany obraz')
        except Exception as ex:
            st.error(f"Nie udało się pobrać obrazu '{img_selected}' ") 
    else:
        st.error(f'Nie ma takiego obrazu {img_selected}')   

#
# MAIN
#
load_dotenv()

if 'evaluated_images' not in st.session_state:
    st.session_state['evaluated_images'] = []

st.set_page_config(page_title="Image Finder", layout="centered")

assure_qdrant_collection_exists()

# OpenAI API key protection
if not st.session_state.get("openai_api_key"):
    if "OPENAI_API_KEY" in env:
        st.session_state["openai_api_key"] = env["OPENAI_API_KEY"]
    else:
        st.info("Dodaj swój klucz API OpenAI aby móc korzystać z tej aplikacji")
        st.session_state["openai_api_key"] = st.text_input("Klucz API", type="password")
        if st.session_state["openai_api_key"]:
            st.rerun()

if not st.session_state.get("openai_api_key"):
    st.stop()

st.title('Aplikacja do przesyłania i wyszukiwania zdjęć')

add_tab, search_tab = st.tabs(["Dodaj zdjęcie", "Wyszukaj zdjęcie"])

with add_tab:
    with st.form('add_image'):
        try:
            CURRENT_IMAGE = ''
            uploaded_file = st.file_uploader('Wybierz zdjęcie', type=['png', 'jpeg', 'jpg'], accept_multiple_files=False)
          
            add_image_submit = st.form_submit_button('Zapisz obraz')
                
            if add_image_submit:
                if uploaded_file is not None:
                    CURRENT_IMAGE = uploaded_file.name
                    img_bytes = BytesIO(uploaded_file.getbuffer())
                    img_bytes.seek(0)
                    image_bytes = img_bytes.getvalue()

                    st.image(img_bytes, caption="Przesłane zdjęcie", use_container_width=True)

                    if image_already_saved(CURRENT_IMAGE) == False:
                        if save_image(img_bytes=img_bytes, img_name="img/" + CURRENT_IMAGE):
                            st.toast("Plik został pomyślnie zapisany!", icon="🎉")

                            st.write(f'open ai key = {get_openai_client()}')
                            with st.spinner('Zaczekaj chwilę...'):
                                photo_text = get_text_from_image(openai_client=get_openai_client(), image_bytes=image_bytes)
                                st.write(photo_text)
                                
                                photo_dict = {
                                    'text':photo_text,
                                    'path':CURRENT_IMAGE,
                                }

                                add_photo_to_qdrant(photo_dict)
                                embedding = get_embedding(text=photo_text, openai_client=get_openai_client())
                                st.toast("Pomyślnie zaktualizowano bazę qdrant!", icon=":material/thumb_up:")
                        else:
                            st.error('Nie udało się zapisać pliku...')
                    else:
                        st.info(f'Ten plik jest już zapisany {CURRENT_IMAGE}')
                else:
                    st.info('Nie wczytano żadnego obrazu')
        except Exception as ex:
            st.error(f'Wystapił nieoczekiwany błąd: {ex}')

with search_tab:
    with st.form('search_img'):
        query = st.text_input('Zapytaj o  zdjęcie, które chcesz znaleźć')
        limit_to =  st.selectbox('Ogranicz ilość wyników do:', [1,2,3,4,5], index=2)
        
        img_source_df =  [{
            'text':'None',
            'path':'No image yet',
            'score':0.0
        },]

        submit = st.form_submit_button("Szukaj obrazów")
        if submit:
            uploaded_file = None
            found_imgs = find_images(query)
            
            # img_source_df.clear()
            
            for item in found_imgs[:limit_to]:
                img_source_df.append({
                    'text': item['text'],
                    'path': str(item['path']).split("\\")[-1],
                    'score' : item['score'],
                })
            
            df = pd.DataFrame(img_source_df)
            df = df[df['path'] != 'No image yet']
            df = df[['path', 'score']].sort_values(by='score', ascending=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
            eval = []

            for idx, row in df.iterrows():
                eval.append(f"{row['score']} : {row['path']}")

            st.session_state['evaluated_images'] = eval

    with st.form('show_img'):
        img_selected = st.selectbox('Wybierz obraz do pobrania', st.session_state['evaluated_images'])

        show_submit = st.form_submit_button('Pobierz obraz', disabled=img_selected is None)
        if show_submit:
            on_image_change(img_selected.split(':')[1].strip())

    
        
