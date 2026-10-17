import streamlit as st
import pandas as pd
import pdfplumber
import re

from io import BytesIO
from reportlab.pdfgen import canvas


# ==========================================
# LEITURA PDF
# ==========================================
def ler_pdf(arquivo):

    texto = ""

    try:
        with pdfplumber.open(arquivo) as pdf:
            for pagina in pdf.pages:
                conteudo = pagina.extract_text()

                if conteudo:
                    texto += conteudo + "\n"

    except Exception as erro:
        texto = str(erro)

    return texto


# ==========================================
# EXTRAÇÃO DE DADOS
# ==========================================
def extrair_dados(texto):

    dados = {
        "Cliente": "",
        "CNPJ": "",
        "Endereco": "",
        "Equipamento": "",
        "Localizacao": "",
        "Serie": "",
        "Patrimonio": "",
        "TAG": "",
        "Data": ""
    }

    linhas = texto.split("\n")

    for linha in linhas:

        l = linha.lower().strip()

        if "cliente" in l and dados["Cliente"] == "":
            dados["Cliente"] = linha

        elif "cnpj" in l and dados["CNPJ"] == "":
            dados["CNPJ"] = linha

        elif ("endereço" in l or "endereco" in l) and dados["Endereco"] == "":
            dados["Endereco"] = linha

        elif "equipamento" in l and dados["Equipamento"] == "":
            dados["Equipamento"] = linha

        elif ("localização" in l or "localizacao" in l) and dados["Localizacao"] == "":
            dados["Localizacao"] = linha

        elif ("série" in l or "serie" in l) and dados["Serie"] == "":
            dados["Serie"] = linha

        elif ("patrimônio" in l or "patrimonio" in l) and dados["Patrimonio"] == "":
            dados["Patrimonio"] = linha

        elif "tag" in l and dados["TAG"] == "":
            dados["TAG"] = linha

    datas = re.findall(r"\d{2}/\d{2}/\d{4}", texto)

    if datas:
        dados["Data"] = datas[0]

    return dados


# ==========================================
# LEITURA DE TABELAS
# ==========================================
def ler_tabelas(arquivo):

    tabelas = []

    try:
        with pdfplumber.open(arquivo) as pdf:

            for pagina in pdf.pages:

                tabs = pagina.extract_tables()

                if tabs:
                    for tabela in tabs:
                        tabelas.append(tabela)

    except Exception:
        pass

    return tabelas


# ==========================================
# GERA PDF
# ==========================================
def gerar_pdf(nome_arquivo, dados):

    buffer = BytesIO()

    pdf = canvas.Canvas(buffer)

    pdf.setTitle("Relatorio")

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(
        50,
        800,
        "RELATORIO DE ANALISE DE CERTIFICADO"
    )

    y = 760

    pdf.setFont("Helvetica", 11)
    pdf.drawString(
        50,
        y,
        f"Arquivo: {nome_arquivo}"
    )

    y -= 30

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(
        50,
        y,
        "DADOS EXTRAIDOS"
    )

    y -= 25

    pdf.setFont("Helvetica", 10)

    for campo, valor in dados.items():

        pdf.drawString(
            50,
            y,
            f"{campo}: {valor}"
        )

        y -= 18

    pdf.save()

    buffer.seek(0)

    return buffer


# ==========================================
# TELA
# ==========================================
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

    if st.button("Processar Certificados"):

        resumo = []

        for arquivo in uploads:

            st.divider()

            st.header(f"📄 {arquivo.name}")

            texto = ler_pdf(arquivo)

            dados_extraidos = extrair_dados(texto)

            st.subheader("Dados Extraídos")
            st.json(dados_extraidos)

            tabelas = ler_tabelas(arquivo)

            if tabelas:

                st.subheader("Tabelas Encontradas")

                for i, tabela in enumerate(tabelas):

                    st.write(f"Tabela {i + 1}")

                    try:
                        df = pd.DataFrame(
                            tabela[1:],
                            columns=tabela[0]
                        )

                        st.dataframe(df)

                    except Exception:
                        st.dataframe(pd.DataFrame(tabela))

            pdf_relatorio = gerar_pdf(
                arquivo.name,
                dados_extraidos
            )

            st.download_button(
                label=f"📄 Baixar Relatório - {arquivo.name}",
                data=pdf_relatorio,
                file_name=f"relatorio_{arquivo.name}.pdf",
                mime="application/pdf"
            )

            with st.expander("Texto Extraído"):

                st.text_area(
                    "Conteúdo",
                    texto,
                    height=300
                )

            resumo.append({
                "Arquivo": arquivo.name,
                "Equipamento": dados_extraidos["Equipamento"],
                "Serie": dados_extraidos["Serie"]
            })

        st.subheader("Resumo")
        st.dataframe(pd.DataFrame(resumo))

else:

    st.info(
        "Envie um ou mais certificados PDF para iniciar."
    )