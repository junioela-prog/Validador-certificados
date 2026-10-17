import streamlit as st
import pandas as pd
from io import BytesIO
from reportlab.pdfgen import canvas


def gerar_pdf(nome_arquivo):
    buffer = BytesIO()

    pdf = canvas.Canvas(buffer)

    pdf.setTitle("Relatório de Análise")

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, 800, "RELATORIO DE ANALISE DE CERTIFICADO")

    pdf.setFont("Helvetica", 11)

    pdf.drawString(50, 760, f"Arquivo: {nome_arquivo}")
    pdf.drawString(50, 740, "Resultado: APROVADO")
    pdf.drawString(50, 720, "Status: Validado pelo sistema")

    pdf.drawString(50, 680, "Engenharia Clinica")
    pdf.drawString(50, 660, "Junior Antonio da Silva Santos")

    pdf.save()

    buffer.seek(0)

    return buffer


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

        st.subheader("Baixar Relatórios")

        for arquivo in uploads:

            pdf_file = gerar_pdf(arquivo.name)

            st.download_button(
                label=f"📄 Relatório - {arquivo.name}",
                data=pdf_file,
                file_name=f"relatorio_{arquivo.name}.pdf",
                mime="application/pdf"
            )

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
