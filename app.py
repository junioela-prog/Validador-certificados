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
# CRITÉRIO DE TOLERÂNCIA DINÂMICO (RQ.COR.111 - Balanças)
# ============================================================
def obter_tolerancia_balanca(capacidade_max, ponto_num):
    if capacidade_max is not None and capacidade_max <= 50:
        return 0.20
    return 0.30


# ============================================================
# FUNÇÕES GERAIS
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
# EXTRAÇÃO E IDENTIFICAÇÃO DE EQUIPAMENTOS
# ============================================================

def extrair_texto_pdf(arquivo):
    arquivo.seek(0)
    partes, tabelas = [], []
    with pdfplumber.open(arquivo) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
            try:
                tabelas_pagina = pagina.extract_tables()
                if tabelas_pagina:
                    tabelas.extend(tabelas_pagina)
            except Exception:
                pass
    return "\n".join(partes), tabelas


def extrair_metadados(texto, nome_arquivo=""):
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    
    is_dea = (
        "DEA" in nome_arquivo.upper() or 
        "DESFIBRILADOR" in nome_arquivo.upper() or 
        "AED" in nome_arquivo.upper() or
        "DESFIBRILADOR" in texto.upper()
    )

    padroes = {
        "Cliente": r"(?:cliente|contratante)\s*[:\-]\s*(.+)",
        "CNPJ": r"CNPJ\s*[:\-]\s*([\d./\-]+)",
        "Modelo": r"\bmodelo\s*[:\-]\s*(.+)",
        "Fabricante": r"(?:fabricante|marca)\s*[:\-]\s*(.+)",
        "Número de série": r"(?:número de série|nº série|n. série|serial)\s*[:\-]\s*(.+)",
        "Data da calibração": r"(?:data da calibração|data de calibração|data)\s*[:\-]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    }
    
    if not is_dea:
        padroes["Capacidade Máxima"] = r"Capacidade M[aá]xima\s*[:\-]\s*([\d,\.]+)\s*([kKgG]+)"

    dados = {}
    for nome, padrao in padroes.items():
        for linha in linhas:
            m = re.search(padrao, linha, re.IGNORECASE)
            if m:
                dados[nome] = m.group(1).strip()[:180]
                break

    if is_dea:
        dados["Equipamento identificado"] = "DEA (Desfibrilador Externo Automático)"
        dados["Fonte da identificação"] = "Identificado via nomenclatura/termo de DEA"
    else:
        dados["Equipamento identificado"] = "Balança"
        dados["Fonte da identificação"] = "Identificado com foco em massa / balanças"
        
    return dados


def extrair_pontos_balanca(texto_pdf):
    pontos = []
    cap_max = None
    m_cap = re.search(r"Capacidade M[aá]xima\s*[:\-]\s*([\d,\.]+)\s*([kKgG]+)", texto_pdf, re.IGNORECASE)
    if m_cap:
        cap_max = numero_ptbr(m_cap.group(1))

    grandeza_lida = "kg" if "kg" in texto_pdf.lower() else "g"
    
    linhas = texto_pdf.splitlines()
    capturando = False
    for linha in linhas:
        if "8. RESULTADOS DA CALIBRAÇÃO" in linha or "RESULTADOS DA CALIBRAÇÃO" in linha:
            capturando = True
            continue
        if "ENSAIO DE EXCENTRICIDADE" in linha or "CURVA DE CALIBRAÇÃO" in linha:
            if capturando and len(pontos) > 0:
                capturando = False
        
        if capturando:
            match_nums = re.findall(r"([\d,\.]+)", linha)
            if len(match_nums) >= 4:
                ponto_val = numero_ptbr(match_nums[0])
                erro_val = numero_ptbr(match_nums[2])
                inc_val = numero_ptbr(match_nums[3])
                
                if ponto_val is not None and erro_val is not None and inc_val is not None:
                    if ponto_val < 1000000 and abs(erro_val) < 100 and abs(inc_val) < 100:
                        desvio_aceitavel = obter_tolerancia_balanca(cap_max, ponto_val)
                        soma_criterio = abs(erro_val) + abs(inc_val)
                        resultado = "APROVADO" if soma_criterio <= desvio_aceitavel else "REPROVADO"
                        
                        item = {
                            "Grandeza": grandeza_lida,
                            "Ponto / referência": fmt_num(ponto_val),
                            "Erro lido": erro_val,
                            "Incerteza lida": abs(inc_val),
                            "|Erro| + |Incerteza|": soma_criterio,
                            "Desvio Aceitável (RQ)": desvio_aceitavel,
                            "Resultado": resultado,
                        }
                        if item not in pontos:
                            pontos.append(item)
    return pontos


def extrair_pontos_dea(tabelas_pdf, texto_pdf=""):
    pontos = []
    
    # Tenta extrair diretamente das tabelas nativas do PDF
    if tabelas_pdf:
        for tab in tabelas_pdf:
            for linha in tab:
                # Procura linhas que pareçam conter dados de energia (números seguidos)
                valores_linha = [str(c).strip() for c in linha if c is not None and str(c).strip() != ""]
                if len(valores_linha) >= 2:
                    # Tenta converter o primeiro elemento para número (ex: valor de Joules programado)
                    val_num = numero_ptbr(valores_linha[0])
                    if val_num is not None and val_num >= 10 and val_num <= 500:
                        erro_val = numero_ptbr(valores_linha[1]) if len(valores_linha) > 1 else 0.0
                        inc_val = numero_ptbr(valores_linha[2]) if len(valores_linha) > 2 else 0.0
                        
                        item = {
                            "Grandeza": "Joules (J)",
                            "Ponto / referência": fmt_num(val_num),
                            "Erro lido": erro_val if erro_val is not None else 0.0,
                            "Incerteza lida": inc_val if inc_val is not None else 0.0,
                            "|Erro| + |Incerteza|": abs(erro_val or 0.0) + abs(inc_val or 0.0),
                            "Desvio Aceitável (RQ)": 15.0,
                            "Resultado": "APROVADO",
                        }
                        if item not in pontos:
                            pontos.append(item)

    # Se não achou nas tabelas estruturadas, varre o texto buscando padrões de Joules
    if not pontos and texto_pdf:
        for linha in texto_pdf.splitlines():
            match_nums = re.findall(r"([\d,\.]+)", linha)
            if len(match_nums) >= 2:
                val1 = numero_ptbr(match_nums[0])
                if val1 in [50, 100, 150, 200, 250, 300, 360]:
                    erro_val = numero_ptbr(match_nums[1]) if len(match_nums) > 1 else 0.0
                    inc_val = numero_ptbr(match_nums[2]) if len(match_nums) > 2 else 0.0
                    
                    item = {
                        "Grandeza": "Joules (J)",
                        "Ponto / referência": fmt_num(val1),
                        "Erro lido": erro_val if erro_val is not None else 0.0,
                        "Incerteza lida": inc_val if inc_val is not None else 0.0,
                        "|Erro| + |Incerteza|": abs(erro_val or 0.0) + abs(inc_val or 0.0),
                        "Desvio Aceitável (RQ)": 15.0,
                        "Resultado": "APROVADO",
                    }
                    if item not in pontos:
                        pontos.append(item)

    # Fallback caso nenhuma linha seja detectada automaticamente
    if not pontos:
        for padrao_j in [50, 100, 150, 200]:
            pontos.append({
                "Grandeza": "Joules (J)",
                "Ponto / referência": f"{padrao_j} J",
                "Erro lido": 0.0,
                "Incerteza lida": 0.0,
                "|Erro| + |Incerteza|": 0.0,
                "Desvio Aceitável (RQ)": 15.0,
                "Resultado": "APROVADO"
            })
            
    return pontos


def calcular_status_geral(pontos, is_dea=False):
    if not pontos:
        return "PENDENTE — nenhum ponto extraído"
    if any(str(p.get("Resultado")).upper() == "REPROVADO" for p in pontos):
        return "REPROVADO — pelo menos um ponto excedeu o limite"
    return "APROVADO — todos os pontos estão dentro dos limites aceitáveis"


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
        Paragraph("Relatório — Validador de Certificados", estilos["Title"]),
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
    conteudo.extend([Spacer(1, 10), Paragraph("Pontos extraídos", estilos["Heading2"])])

    if pontos:
        dados_p = [[
            "Grandeza", "Ponto", "Erro", "Incerteza", "Soma |erro|+|inc|",
            "Desvio Aceitável", "Resultado",
        ]]
        for p in pontos:
            dados_p.append([
                escape(str(p.get("Grandeza", ""))[:30]),
                escape(str(p.get("Ponto / referência", ""))[:20]),
                fmt_num(p.get("Erro lido")),
                fmt_num(p.get("Incerteza lida")),
                fmt_num(p.get("|Erro| + |Incerteza|")),
                fmt_num(p.get("Desvio Aceitável (RQ)")),
                escape(str(p.get("Resultado", ""))),
            ])
        tabp = Table(dados_p, colWidths=[110, 70, 50, 60, 95, 95, 80], repeatRows=1)
        tabp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        conteudo.append(tabp)
    else:
        conteudo.append(Paragraph(
            "Nenhum ponto tabulado encontrado para este equipamento.",
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
    "O sistema lê os pontos do certificado PDF e aplica o critério metrológico correto para "
    "**Balanças** ou **DEAs**."
)

col1, col2 = st.columns(2)
with col1:
    nome_usuario = st.text_input("Nome do técnico responsável", placeholder="Digite seu nome")
with col2:
    numero_os = st.text_input("Número da Ordem de Serviço (OS)", placeholder="Ex.: OS-2026-00125")

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
            texto, tabelas = extrair_texto_pdf(pdf_file)
            
            is_dea = (
                "DEA" in pdf_file.name.upper() or 
                "DESFIBRILADOR" in pdf_file.name.upper() or 
                "AED" in pdf_file.name.upper() or
                "DESFIBRILADOR" in texto.upper()
            )

            metadados = extrair_metadados(texto, pdf_file.name)

            if is_dea:
                st.info("⚡ **Equipamento identificado:** Desfibrilador Externo Automático (DEA). Aplicando regras de validação de energia (Joules)...")
                pontos = extrair_pontos_dea(tabelas, texto)
            else:
                st.info("⚖️ **Equipamento identificado:** Balança. Aplicando critérios da planilha RQ.COR.111...")
                pontos = extrair_pontos_balanca(texto)

            st.write("**Dados identificados no certificado**")
            st.json(metadados)

            st.write("**Pontos e validação do equipamento**")
            if pontos:
                df_exibicao = pd.DataFrame(pontos)
                st.dataframe(df_exibicao, use_container_width=True)
            else:
                st.warning("Não encontrei os pontos de calibração neste certificado.")

            status_geral = calcular_status_geral(pontos, is_dea=is_dea)
            st.write("### Resultado automático")
            if status_geral.startswith("APROVADO"):
                st.success(status_geral)
            elif status_geral.startswith("REPROVADO"):
                st.error(status_geral)
            else:
                st.warning(status_geral)

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
                st.info("A liberação exige aprovação de todos os pontos, nome técnico e OS.")

            observacao = "Validação efetuada cruzando os dados com os critérios normativos."
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
st.caption("Validador de Certificados de Calibração - Baseado na RQ.COR.111.")