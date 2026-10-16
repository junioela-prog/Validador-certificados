import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Validador de Certificados",layout="wide")

st.title("Validador de Certificados - Engenharia Clínica")

uploads=st.file_uploader("Envie um ou mais certificados PDF",type=['pdf'],accept_multiple_files=True)

if uploads:
    dados=[]
    for arq in uploads:
        dados.append({"Arquivo":arq.name,"Status":"Aguardando validação","Resultado":"Pendente"})
    df=pd.DataFrame(dados)
    st.dataframe(df,use_container_width=True)

    if st.button("Processar Certificados"):
        resultados=[]
        for arq in uploads:
            resultados.append({"Arquivo":arq.name,"Resultado":"APROVADO (protótipo)"})
        st.success(f"{len(resultados)} certificado(s) processado(s).")
        st.dataframe(pd.DataFrame(resultados),use_container_width=True)
        csv=pd.DataFrame(resultados).to_csv(index=False).encode()
        st.download_button('Baixar relatório CSV',csv,'relatorio_certificados.csv','text/csv')
else:
    st.info('Envie certificados PDF para iniciar.')

st.markdown(