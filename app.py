import re
from io import BytesIO
from datetime import datetime
from html import escape

import pandas as pd
import pdfplumber
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from motor_rq111 import (
    carregar_regras,
    fmt_num,
    identificar_equipamento_dinamico,
    validar_pontos_dinamico,
)

st.set_page_config(page_title="Validador de Certificados", page_icon="📄", layout="wide")


@st.cache_data
def obter_regras():
    return carregar_regras("regras_rq111.json")


def extrair_texto_pdf(arquivo):
    arquivo.seek(0)
    partes = []
    with pdfplumber.open(arquivo) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
    return "\n".join(partes)


def extrair_metadados(texto, nome_arquivo, regras, tipo_manual="Automático"):
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    padroes = {
        "Cliente": r"(?:cliente|contratante)\s*[:\-]\s*(.+)",
        "CNPJ": r"CNPJ\s*[:\-]\s*([\d./\-]+)",
        "Modelo": r"\bmodelo\s*[:\-]\s*(.+)",
        "Fabricante": r"(?:fabricante|marca)\s*[:\-]\s*(.+)",
        "Número de série": r"(?:número de série|nº série|n. série|serial)\s*[:\-]\s*(.+)",
        "Capacidade Máxima": r"Capacidade M[aá]xima\s*[:\-]\s*([\d,\.]+)\s*([kKgG]+)",
        "Data da calibração": r"(?:data da calibração|data de calibração|data)\s*[:\-]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    }

    dados = {}
    for nome, padrao in padroes.items():
        for linha in linhas:
            m = re.search(padrao, linha, re.IGNORECASE)
            if m:
                dados[nome] = m.group(1).strip()[:180]
                break

    eq = identificar_equipamento_dinamico(texto, nome_arquivo, regras, tipo_manual)
    dados["Equipamento identificado"] = eq
    dados["Família (RQ.COR.111)"] = regras.get(eq, {}).get("familia", "Não informada")
    dados["Fonte da identificação"] = "Manual" if tipo_manual != "Automático" else "Automática (RQ.COR.111)"
    return dados


def calcular_status_geral(pontos):
    if not pontos:
        return "PENDENTE — nenhum ponto extraído"
    if any(p.get("CONCLUSAO") == "Reprovado" for p in pontos):
        return "REPROVADO — pelo menos um ponto excedeu o limite/desvio aceitável"
    return "APROVADO — todos os pontos estão dentro dos limites e desvios aceitáveis"


def gerar_relatorio_pdf(nome_usuario, numero_os, arquivo_nome, metadados,
                        pontos, status_geral, observacao):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24,
        topMargin=24, bottomMargin=24
    )
    estilos = getSampleStyleSheet()
    conteudo = [
        Paragraph("Relatório — Validador de Certificados (RQ.COR.111)", estilos["Title"]),
        Spacer(1, 8),
        Paragraph(f"<b>Técnico responsável:</b> {escape(nome_usuario or 'Não informado')}", estilos["Normal"]),
        Paragraph(f"<b>Ordem de Serviço:</b> {escape(numero_os or 'Não informada')}", estilos["Normal"]),
        Paragraph(f"<b>Arquivo:</b> {escape(arquivo_nome)}", estilos["Normal"]),
        Paragraph(f"<b>Data de geração:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos["Normal"]),
        Paragraph(f"<b>Resultado:</b> {escape(status_geral)}", estilos["Normal"]),
        Spacer(1, 8),
        Paragraph("Dados identificados no certificado", estilos["Heading2"]),
    ]

    dados = [["Campo", "Valor"]]
    dados.extend([[escape(str(k)), escape(str(v))] for k, v in metadados.items()])
    tab = Table(dados, colWidths=[170, 450], repeatRows=1)
    tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    conteudo.append(tab)
    conteudo.extend([Spacer(1, 10), Paragraph("Pontos extraídos e Validação", estilos["Heading2"])])

    if pontos:
        dados_p = [[
            "Grandeza", "Unid.", "Nominal", "Lido", "Lim. Mín.", "Lim. Máx.",
            "Erro", "Incerteza", "Erro Total", "Desvio Aceit.", "Conclusão"
        ]]
        for p in pontos:
            dados_p.append([
                str(p.get("Grandeza", "")),
                str(p.get("Unidade", "")),
                str(p.get("Ponto Nominal", "")),
                str(p.get("Ponto Lido", "")),
                str(p.get("Limite Mínimo", "")),
                str(p.get("Limite Máximo", "")),
                fmt_num(p.get("Erro")),
                fmt_num(p.get("Incerteza")),
                fmt_num(p.get("Erro Total")),
                fmt_num(p.get("Desvio Aceitável")),
                str(p.get("CONCLUSAO", "")),
            ])

        tabp = Table(dados_p, repeatRows=1)
        tabp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        conteudo.append(tabp)
    else:
        conteudo.append(Paragraph("Nenhum ponto extraído automaticamente.", estilos["Normal"]))

    conteudo.extend([
        Spacer(1, 10),
        Paragraph("Observação", estilos["Heading2"]),
        Paragraph(escape(observacao), estilos["Normal"]),
    ])
    doc.build(conteudo)
    buffer.seek(0)
    return buffer


st.title("📄 Validador de Certificados de Calibração")
st.write(
    "Sistema Validador de Calibração — Garantia de Conformidade com a ABNT NBR ISO/IEC 17025 e RQ.COR.111."
)

try:
    regras_rq111 = obter_regras()
except Exception as e:
    st.error(f"Erro ao carregar regras_rq111.json: {e}")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    nome_usuario = st.text_input("Nome do técnico responsável", placeholder="Digite seu nome")
with col2:
    numero_os = st.text_input("Número da Ordem de Serviço (OS)", placeholder="Ex.: OS-2026-00125")

opcoes_equipamentos = ["Automático"] + list(regras_rq111.keys())
tipo_forçado = st.selectbox(
    "Tipo de Equipamento (Lista carregada automaticamente da RQ.COR.111)",
    opcoes_equipamentos,
)

pdf_files = st.file_uploader(
    "Envie os certificados de calibração (.pdf)",
    type=["pdf"],
    accept_multiple_files=True,
)

if pdf_files:
    for pdf_file in pdf_files:
        st.divider()
        st.subheader(f"Certificado: {pdf_file.name}")
        try:
            texto = extrair_texto_pdf(pdf_file)
            metadados = extrair_metadados(texto, pdf_file.name, regras_rq111, tipo_forçado)
            equipamento = metadados.get("Equipamento identificado", "")
            pontos = validar_pontos_dinamico(texto, equipamento, regras_rq111)

            st.write("**Dados identificados no certificado**")
            st.json(metadados)
            st.info(f"Categoria aplicada: **{equipamento}**")

            with st.expander("Conferir texto extraído do PDF (diagnóstico)"):
                st.text_area(
                    "Texto lido do certificado",
                    value=texto,
                    height=220,
                    key=f"texto_extraido_{re.sub(r'[^A-Za-z0-9]', '_', pdf_file.name)}",
                )

            if pontos:
                st.write("**Tabela de Validação de Pontos**")
                df_exibicao = pd.DataFrame(pontos)
                st.dataframe(df_exibicao, use_container_width=True)
            else:
                st.warning("Nenhum ponto de calibração foi encontrado neste certificado.")

            status_geral = calcular_status_geral(pontos)
            st.write("### Resultado automático")
            if status_geral.startswith("APROVADO"):
                st.success(status_geral)
            elif status_geral.startswith("PENDENTE"):
                st.warning(status_geral)
            else:
                st.error(status_geral)

            st.write("### Liberação técnica")
            if status_geral.startswith("APROVADO") and nome_usuario.strip() and numero_os.strip():
                confirmar = st.checkbox(
                    "Conferi os dados extraídos, o equipamento e os limites calculados.",
                    key=f"conferir_{re.sub(r'[^A-Za-z0-9]', '_', pdf_file.name)}"
                )
                if confirmar:
                    st.success("Conferência registrada nesta sessão.")
                else:
                    st.info("Marque a conferência após revisar os dados.")
            else:
                st.info("A liberação exige aprovação de todos os pontos, nome do técnico e OS.")

            observacao = (
                f"Validação efetuada para {equipamento} conforme norma ISO/IEC 17025 "
                "e RQ.COR.111."
            )
            relatorio = gerar_relatorio_pdf(
                nome_usuario, numero_os, pdf_file.name, metadados,
                pontos, status_geral, observacao
            )
            nome_seguro = re.sub(r"[^A-Za-z0-9_-]", "_", pdf_file.name)
            st.download_button(
                "📥 Baixar relatório PDF",
                data=relatorio,
                file_name=f"relatorio_{nome_seguro}.pdf",
                mime="application/pdf",
                key=f"relatorio_{nome_seguro}"
            )
        except Exception as e:
            st.error(f"Erro ao processar este certificado: {e}")

st.divider()
st.caption(
    "Validador de Certificados de Calibração — Atendimento à Norma ISO/IEC 17025 e RQ.COR.111."
)