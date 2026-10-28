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

st.set_page_config(page_title="Validador de Certificados", page_icon="📄", layout="wide")

# ============================================================
# FUNÇÕES GERAIS DE SUPORTE
# ============================================================

def normalizar(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    texto = str(valor).strip().lower()
    substituicoes = {
        "º": "o", "ª": "a", "µ": "u", "μ": "u", "ç": "c",
        "ã": "a", "á": "a", "à": "a", "â": "a", "é": "e",
        "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u",
    }
    for antigo, novo in substituicoes.items():
        texto = texto.replace(antigo, novo)
    texto = re.sub(r"[^a-z0-9,./%°+\-]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def numero_ptbr(valor):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)

    s = str(valor).strip().replace("−", "-").replace("–", "-")
    if not s:
        return None
    s = re.sub(r"[^0-9,\.eE+\-]", "", s)
    if not s or not re.search(r"\d", s):
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except ValueError:
        return None


def fmt_num(valor):
    if valor is None:
        return "Não identificado"
    try:
        if pd.isna(valor):
            return "Não identificado"
    except (TypeError, ValueError):
        pass
    return f"{float(valor):.8g}".replace(".", ",")


# ============================================================
# IDENTIFICAÇÃO E EXTRAÇÃO ROBUSTA
# ============================================================

def extrair_texto_pdf(arquivo):
    arquivo.seek(0)
    partes = []
    with pdfplumber.open(arquivo) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
    return "\n".join(partes)


def identificar_equipamento(texto, nome_arquivo="", tipo_manual="Automático"):
    if tipo_manual and tipo_manual != "Automático":
        return tipo_manual

    m_cap = re.search(r"Capacidade M[aá]xima\s*[:\-]\s*([\d,\.]+)\s*([kKgG]+)", texto, re.IGNORECASE)
    cap_val = numero_ptbr(m_cap.group(1)) if m_cap else 0.0

    nome_norm = normalizar(nome_arquivo)
    if "balanca" in nome_norm or "ubb" in nome_norm:
        if cap_val > 0 and cap_val <= 30:
            return "Balança Pediátrica/Neonatal"
        if cap_val >= 150:
            return "Balança Adulta"
        if "pediatrica" in nome_norm or "neo" in nome_norm:
            return "Balança Pediátrica/Neonatal"
        if "analitica" in nome_norm:
            return "Balança Analítica"
        return "Balança Adulta"

    if "oximetro" in nome_norm or "spo2" in nome_norm:
        return "Oxímetro de pulso"
    if "dea" in nome_norm or "desfibrilador" in nome_norm or "cardioversor" in nome_norm:
        return "DEA / Cardioversor"

    if cap_val > 0 and cap_val <= 30:
        return "Balança Pediátrica/Neonatal"
    if cap_val >= 150:
        return "Balança Adulta"
    if "analitica" in normalizar(texto):
        return "Balança Analítica"
    return "Balança Adulta"


def extrair_metadados(texto, nome_arquivo="", tipo_manual="Automático"):
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

    eq = identificar_equipamento(texto, nome_arquivo, tipo_manual)
    dados["Equipamento identificado"] = eq
    dados["Fonte da identificação"] = "Automática / Capacidade"
    return dados


def extrair_pontos_certificado(texto_pdf, equipamento):
    pontos = []
    linhas = texto_pdf.splitlines()
    eq_l = equipamento.lower()
    capturando_tabela = False

    for linha in linhas:
        l_low = linha.lower()

        if "/" in linha or re.search(r"\b20[2-3]\d\b", linha):
            continue

        if "resultados da calibração" in l_low or "valor indicado" in l_low or "incerteza de medição" in l_low:
            capturando_tabela = True
            continue

        if any(termo in l_low for termo in ["carga mínima", "capacidade máxima", "resolução (d)", "resolução (e)", "fator de abrangência"]):
            continue

        if "***** Fim" in l_low or "observações" in l_low:
            capturando_tabela = False

        if capturando_tabela:
            match_nums = re.findall(r"([−\-\d,\.]+)", linha)
            if len(match_nums) >= 4:
                val1 = numero_ptbr(match_nums[0])
                val2 = numero_ptbr(match_nums[1])
                erro_val = numero_ptbr(match_nums[2])
                inc_val = numero_ptbr(match_nums[3])

                if val1 is not None and val2 is not None and inc_val is not None:
                    if "dea" in eq_l or "cardioversor" in eq_l:
                        grandeza = "Energia Descarregada"
                        unidade = "J"
                        ponto_nominal = val2
                        ponto_lido = val1
                        
                        tolerancia = ponto_nominal * 0.15
                        erro_real = ponto_lido - ponto_nominal
                        erro_total = abs(erro_real) + abs(inc_val)
                        
                        item = {
                            "Ponto Nominal": fmt_num(ponto_nominal),
                            "Ponto Lido": fmt_num(ponto_lido),
                            "Unidade": unidade,
                            "Grandeza": grandeza,
                            "Erro": erro_real,
                            "Incerteza da Medição": abs(inc_val),
                            "Erro Total": erro_total,
                            "Erro Aceitável": tolerancia,
                            "CONCLUSAO": "Aprovado" if erro_total <= tolerancia else "Reprovado",
                        }
                    else:
                        ponto_val = val1
                        if ponto_val <= 0 or ponto_val > 1000:
                            continue
                        if abs(erro_val) > 50 or abs(inc_val) > 50:
                            continue

                        if "oximetro" in eq_l:
                            grandeza = "Frequência Cardíaca da Oximetria" if ("bpm" in l_low or ponto_val > 25) else "Saturação do Oxigênio (SpO2)"
                            unidade = "BPM" if grandeza.startswith("Frequência") else "%SpO2"
                            tolerancia = 5.0 if unidade == "BPM" else 3.0
                        elif "analitica" in eq_l:
                            grandeza = "Kilos"
                            unidade = "g" if "g" in l_low else "kg"
                            tolerancia = ponto_val * 0.005
                        elif "pediatrica" in eq_l or "neo" in eq_l:
                            grandeza = "Kilos"
                            unidade = "g" if "g" in l_low else "kg"
                            tolerancia = 0.2
                        else:  # Balança Adulta
                            grandeza = "Kilos"
                            unidade = "g" if "g" in l_low else "kg"
                            tolerancia = 0.3

                        erro_total = abs(erro_val) + abs(inc_val)
                        item = {
                            "Pontos": fmt_num(ponto_val),
                            "Unidade": unidade,
                            "Grandeza": grandeza,
                            "Erro": erro_val,
                            "Incerteza da Medição": abs(inc_val),
                            "Erro Total": erro_total,
                            "Erro Aceitável": tolerancia,
                            "CONCLUSAO": "Aprovado" if erro_total <= tolerancia else "Reprovado",
                        }

                    if item not in pontos:
                        pontos.append(item)
    return pontos


def calcular_status_geral(pontos):
    if not pontos:
        return "PENDENTE — nenhum ponto extraído"
    if any(p.get("CONCLUSAO") == "Reprovado" for p in pontos):
        return "REPROVADO — pelo menos um ponto excedeu o erro aceitável"
    return "APROVADO — todos os pontos estão dentro do erro aceitável"


# ============================================================
# RELATÓRIO PDF
# ============================================================

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
    tab = Table(dados, colWidths=[150, 430], repeatRows=1)
    tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    conteudo.append(tab)
    conteudo.extend([Spacer(1, 10), Paragraph("Pontos extraídos e Validação", estilos["Heading2"])])

    if pontos:
        primeiro = pontos[0]
        if "Ponto Nominal" in primeiro:
            dados_p = [[
                "Ponto Nominal", "Ponto Lido", "Unidade", "Grandeza", "Erro", "Incerteza",
                "Erro Total", "Erro Aceitável", "Conclusão"
            ]]
            for p in pontos:
                dados_p.append([
                    str(p.get("Ponto Nominal", "")),
                    str(p.get("Ponto Lido", "")),
                    str(p.get("Unidade", "")),
                    str(p.get("Grandeza", "")),
                    fmt_num(p.get("Erro")),
                    fmt_num(p.get("Incerteza da Medição")),
                    fmt_num(p.get("Erro Total")),
                    fmt_num(p.get("Erro Aceitável")),
                    str(p.get("CONCLUSAO", "")),
                ])
        else:
            dados_p = [[
                "Pontos", "Unidade", "Grandeza", "Erro", "Incerteza",
                "Erro Total", "Erro Aceitável", "Conclusão"
            ]]
            for p in pontos:
                dados_p.append([
                    str(p.get("Pontos", "")),
                    str(p.get("Unidade", "")),
                    str(p.get("Grandeza", "")),
                    fmt_num(p.get("Erro")),
                    fmt_num(p.get("Incerteza da Medição")),
                    fmt_num(p.get("Erro Total")),
                    fmt_num(p.get("Erro Aceitável")),
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
        conteudo.append(Paragraph(
            "Nenhum ponto extraído automaticamente.",
            estilos["Normal"]
        ))

    conteudo.extend([
        Spacer(1, 10),
        Paragraph("Observação", estilos["Heading2"]),
        Paragraph(escape(observacao), estilos["Normal"]),
    ])
    doc.build(conteudo)
    buffer.seek(0)
    return buffer


# ============================================================
# INTERFACE
# ============================================================

st.title("📄 Validador de Certificados de Calibração")
st.write(
    "Sistema Validador de Calibração — Garantia de Conformidade com a ABNT NBR ISO/IEC 17025 e RQ.COR.111."
)

col1, col2 = st.columns(2)
with col1:
    nome_usuario = st.text_input("Nome do técnico responsável", placeholder="Digite seu nome")
with col2:
    numero_os = st.text_input("Número da Ordem de Serviço (OS)", placeholder="Ex.: OS-2026-00125")

tipo_forçado = st.selectbox(
    "Tipo de Equipamento (Deixe em 'Automático' para detectar pela capacidade e nome)",
    ["Automático", "Balança Adulta", "Balança Pediátrica/Neonatal", "Balança Analítica", "DEA / Cardioversor", "Oxímetro de pulso"]
)

pdf_files = st.file_uploader(
    "Envie os certificados de calibração (.pdf)",
    type=["pdf"],
    accept_multiple_files=True
)

if pdf_files:
    for pdf_file in pdf_files:
        st.divider()
        st.subheader(f"Certificado: {pdf_file.name}")
        try:
            texto = extrair_texto_pdf(pdf_file)
            metadados = extrair_metadados(texto, pdf_file.name, tipo_forçado)
            equipamento = metadados.get("Equipamento identificado", "Balança Adulta")
            pontos = extrair_pontos_certificado(texto, equipamento)

            st.write("**Dados identificados no certificado**")
            st.json(metadados)
            st.info(f"Categoria aplicada: **{equipamento}**")

            if pontos:
                st.write("**Tabela de Validação de Pontos**")
                df_exibicao = pd.DataFrame(pontos)
                st.dataframe(df_exibicao, use_container_width=True)
            else:
                st.warning("Não encontrei os pontos de calibração neste certificado.")

            status_geral = calcular_status_geral(pontos)
            st.write("### Resultado automático")
            if status_geral.startswith("APROVADO"):
                st.success(status_geral)
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

            observacao = f"Validação efetuada para {equipamento} conforme norma ISO/IEC 17025 e RQ.COR.111."
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
st.caption("Validador de Certificados de Calibração — Atendimento à Norma ISO/IEC 17025 e RQ.COR.111.")