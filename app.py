import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Validador de Certificados",
    layout="wide"
)

st.title("Validador de Certificados - Engenharia Clínica")

uploads = st.file_uploader(
    "Envie um ou mais certificados PDF",
    type=["pdf"],
    accept_multiple_files=True
)

if uploads:

    dados = []

    for arquivo in uploads:
        dados.append({
            "Arquivo": arquivo.name,
            "Status": "Aguardando validação",
            "Resultado": "Pendente"
        })

    df = pd.DataFrame(dados)

    st.subheader("Arquivos carregados")
    st.dataframe(df)

    if st.button("Processar Certificados"):

        resultados = []

        for arquivo in uploads:
            resultados.append({
                "Arquivo": arquivo.name,
                "Resultado": "APROVADO (Protótipo)"
            })

        resultado_df = pd.DataFrame(resultados)

        st.success(
            f"{len(resultados)} certificado(s) processado(s)"
        )

        st.dataframe(resultado_df)

else:
    st.info(
        "Envie um ou mais certificados PDF para iniciar."
    )

st.markdown("""
### Próximas funcionalidades

- Leitura automática dos PDFs
- Integração com RQ.COR.111
- Aprovação e reprovação automática
- Geração de parecer PDF
- Dashboard de indicadores
- Histórico de calibrações
""")
