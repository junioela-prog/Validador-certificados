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
# TABELA DE TOLERÂNCIAS OFICIAIS (RQ.COR.111 - 20 Abas)
# ============================================================
LIMITES_EQUIPAMENTOS = {
    "Oxímetro de pulso": {
        "tipo_padrao": "misto_oximetro",
    },
    "Monitor multiparâmetros": {
        "tipo_padrao": "monitor_multiparamentros",
    },
    "Monitor de triagem": {
        "tipo_padrao": "monitor_triagem",
    },
    "Termômetro": {
        "limite_absoluto": 1.5,
    },
    "Termômetro infravermelho": {
        "limite_absoluto": 1.0,
    },
    "Termohigrômetro": {
        "limite_absoluto": 1.5,
    },
    "Esfigmomanômetro": {
        "limite_absoluto": 3.0,
    },
    "DEA": {
        "percentual": 15.0,
    },
    "Desfibrilador": {
        "percentual": 15.0,
    },
    "Balança": {
        "limite_absoluto": 0.05,
    },
    "Centrífuga": {
        "percentual": 5.0,
    },
    "Bisturi eletrônico": {
        "percentual": 15.0,
    },
    "Bomba de infusão": {
        "limite_absoluto": 1.5,
    },
    "Eletrocardiógrafo": {
        "limite_absoluto": 5.0,
    },
    "Esteira ergómetrica": {
        "percentual": 8.0,
    },
    "Estufa": {
        "limite_absoluto": 1.5,
    },
    "Micropipetas": {
        "percentual": 3.0,
    },
    "Câmara de Conservação": {
        "limite_absoluto": 1.5,
    },
    "Ventilador pulmonar": {
        "percentual": 10.0,
    },
    "Incubadora Neonatal": {
        "limite_absoluto": 1.5,
    },
    "Laser Vermelho e Infravermelho": {
        "percentual": 20.0,
    },
    "Espirômetro": {
        "percentual": 10.0,
    },
}


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
# EXTRAÇÃO E IDENTIFICAÇÃO DE EQUIPAMENTOS (20 ABAS)
# ============================================================

def extrair_texto_pdf(arquivo):
    arquivo.seek(0)
    partes, tabelas = [], []
    with pdfplumber.open(arquivo) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text() or "")
            try:
                tabelas.extend(pagina.extract_tables() or [])
            except Exception:
                pass
    return "\n".join(partes), tabelas


def identificar_equipamento(texto, nome_arquivo=""):
    texto_norm = normalizar(texto)
    arquivo_norm = normalizar(nome_arquivo)
    
    rotulos = [
        r"^\s*(?:tipo de equipamento|equipamento|instrumento|item calibrado|"
        r"descricao do equipamento|descrição do equipamento)\s*[:\-]\s*(.+)$"
    ]
    
    candidatos = []
    for linha in texto.splitlines():
        linha_limpa = linha.strip()
        if not linha_limpa:
            continue
        for padrao in rotulos:
            m = re.search(padrao, linha_limpa, re.IGNORECASE)
            if m:
                candidatos.append(m.group(1).strip()[:180])
                break

    fonte = normalizar(" ".join(candidatos)) if candidatos else ""
    if not fonte:
        fonte = arquivo_norm

    regras = [
        ("Monitor multiparâmetros", ("monitor multiparametros", "monitor multiparametro", "monitor multiparâmetros")),
        ("Monitor de triagem", ("monitor de triagem", "monitor triagem")),
        ("Termômetro infravermelho", ("termometro infravermelho", "termometro infra vermelho", "termometro IR", "infrared thermometer")),
        ("Termohigrômetro", ("termohigrometro", "termo higrometro", "termo-higrometro")),
        ("DEA", ("desfibrilador externo automatico", " dea ", "dea")),
        ("Desfibrilador", ("desfibrilador",)),
        ("Termômetro", ("termometro", "termometro digital", "termometro de contato")),
        ("Oxímetro de pulso", ("oximetro", "oximetro de pulso", "pulse oximeter")),
        ("Esfigmomanômetro", ("esfigmomanometro", "pni", "pressao nao invasiva")),
        ("Balança", ("balanca", "balanca digital", "balanca de bioimpedancia")),
        ("Centrífuga", ("centrifuga", "excelsa")),
        ("Bisturi eletrônico", ("bisturi", "eletrocauterio")),
        ("Bomba de infusão", ("bomba de infusao", "bomba infusora", "bomba de seringa")),
        ("Eletrocardiógrafo", ("eletrocardiografo",)),
        ("Esteira ergómetrica", ("esteira ergometrica", "esteira")),
        ("Estufa", ("estufa", "bloco termico", "banho maria", "incubadora biologica", "berço aquecido")),
        ("Micropipetas", ("micropipeta", "multipette", "reference")),
        ("Câmara de Conservação", ("camara de conservacao", "freezer", "nexxto")),
        ("Ventilador pulmonar", ("ventilador pulmonar", "auto fluxo", "oxylog")),
        ("Incubadora Neonatal", ("incubadora neonatal",)),
        ("Laser Vermelho e Infravermelho", ("laser vermelho", "laser infravermelho")),
        ("Espirômetro", ("espirometro",)),
    ]

    for nome, termos in regras:
        for termo in termos:
            termo_n = normalizar(termo)
            if fonte and (fonte == termo_n or termo_n in fonte):
                return nome, "Identificado no campo do equipamento/nome do arquivo"

    if not candidatos:
        prioridade = [
            ("Monitor multiparâmetros", r"monitor\s+multi[\-\s]?par[aâ]metros"),
            ("Monitor de triagem", r"monitor\s+de\s+triagem"),
            ("Termômetro infravermelho", r"term[oô]metro\s*(?:infra[\-\s]?vermelho|infravermelho)|infrared thermometer"),
            ("Termohigrômetro", r"termo[\-\s]?higr[oô]metro"),
            ("Oxímetro de pulso", r"ox[ií]metro(?:\s+de\s+pulso)?|pulse oximeter"),
            ("Esfigmomanômetro", r"esfigmoman[oô]metro|press[aã]o n[aã]o invasiva"),
            ("Bomba de infusão", r"bomba\s+(?:de\s+)?infus[aã]o|bomba infusora"),
            ("Desfibrilador", r"desfibrilador"),
            ("Eletrocardiógrafo", r"eletrocardiógrafo"),
            ("Esteira ergómetrica", r"esteira ergométrica"),
            ("Micropipetas", r"micropipeta"),
            ("Ventilador pulmonar", r"ventilador pulmonar"),
            ("Incubadora Neonatal", r"incubadora neonatal"),
            ("Laser Vermelho e Infravermelho", r"laser"),
            ("Espirômetro", r"espirômetro"),
            ("Termômetro", r"term[oô]metro"),
            ("Balança", r"balan[cç]a"),
            ("Centrífuga", r"centr[ií]fuga"),
            ("Bisturi eletrônico", r"bisturi|elétrocautério"),
        ]
        for nome, padrao in prioridade:
            if re.search(padrao, texto, re.IGNORECASE):
                if nome == "Desfibrilador" and re.search(
                    r"desfibrilador\s+externo\s+autom[aá]tico|\bDEA\b", texto, re.IGNORECASE
                ):
                    return "DEA", "Identificado no texto do certificado"
                return nome, "Identificado no texto do certificado"

    return "Não identificado com segurança", "Confira o campo Equipamento/Instrumento no PDF"


def extrair_metadados(texto, nome_arquivo=""):
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    padroes = {
        "Cliente": r"(?:cliente|contratante)\s*[:\-]\s*(.+)",
        "CNPJ": r"CNPJ\s*[:\-]\s*([\d./\-]+)",
        "Modelo": r"\bmodelo\s*[:\-]\s*(.+)",
        "Fabricante": r"(?:fabricante|marca)\s*[:\-]\s*(.+)",
        "Número de série": r"(?:número de série|nº série|n. série|serial)\s*[:\-]\s*(.+)",
        "Patrimônio": r"(?:patrimônio|nº patrimônio)\s*[:\-]\s*(.+)",
        "TAG": r"\bTAG\s*[:\-]\s*(.+)",
        "Data da calibração": r"(?:data da calibração|data de calibração|data)\s*[:\-]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    }
    dados = {}
    for nome, padrao in padroes.items():
        for linha in linhas:
            m = re.search(padrao, linha, re.IGNORECASE)
            if m:
                dados[nome] = m.group(1).strip()[:180]
                break

    equipamento, fonte = identificar_equipamento(texto, nome_arquivo)
    dados["Equipamento identificado"] = equipamento
    dados["Fonte da identificação"] = fonte
    return dados


def tabelas_pdf_para_df(tabelas):
    saida = []
    for num_tabela, tabela in enumerate(tabelas, start=1):
        if not tabela or len(tabela) < 2:
            continue
        linhas = [[(c or "").strip().replace("\n", " ") for c in linha] for linha in tabela]
        cabecalhos = []
        for i, c in enumerate(linhas[0]):
            nome = c or f"Coluna {i + 1}"
            if nome in cabecalhos:
                nome = f"{nome} ({i + 1})"
            cabecalhos.append(nome)
        try:
            df = pd.DataFrame(linhas[1:], columns=cabecalhos)
            if not df.empty:
                df.attrs["numero_tabela_pdf"] = num_tabela
                saida.append(df)
        except Exception:
            continue
    return saida


def localizar_colunas_resultado(df):
    nomes = {c: normalizar(c) for c in df.columns}
    col_erro = next((c for c, n in nomes.items() if re.search(r"\berro\b", n)), None)
    col_inc = next((c for c, n in nomes.items() if "incerteza" in n), None)

    termos_ponto = (
        "ponto", "referencia", "nominal", "setpoint",
        "valor indicado no padrao", "valor do padrao",
        "indicacao do padrao", "valor de referencia",
    )
    col_ponto = next(
        (c for c, n in nomes.items()
         if any(t in n for t in termos_ponto)
         and "erro" not in n and "incerteza" not in n
         and "instrumento" not in n),
        None
    )
    if col_ponto is None:
        col_ponto = next(
            (c for c, n in nomes.items()
             if ("padrao" in n or "referencia" in n or "ponto" in n)
             and "erro" not in n and "incerteza" not in n
             and "instrumento" not in n),
            None
        )
    return col_erro, col_inc, col_ponto


def obter_limite(equipamento, ponto_texto, grandeza=""):
    config = LIMITES_EQUIPAMENTOS.get(equipamento)
    ponto_num = numero_ptbr(ponto_texto)
    
    if "oximetro" in normalizar(equipamento) or "frequencia cardiaca" in normalizar(grandeza) or "saturacao" in normalizar(grandeza):
        g_norm = normalizar(grandeza)
        if "frequencia" in g_norm or "bpm" in g_norm:
            return 5.0
        elif "saturacao" in g_norm or "spo2" in g_norm:
            if ponto_num is not None:
                return abs(ponto_num) * (3.0 / 100.0)
            return 3.0

    if not config:
        return None

    if ponto_num is None:
        return None

    if "percentual" in config:
        p = config["percentual"]
        return abs(ponto_num) * (p / 100.0)

    if "limite_absoluto" in config:
        return config["limite_absoluto"]

    tipo = config.get("tipo_padrao")
    if tipo in ["misto_oximetro", "monitor_multiparamentros", "monitor_triagem"]:
        txt_lower = normalizar(ponto_texto)
        if "temp" in txt_lower or (35 <= ponto_num <= 42 and "bpm" not in txt_lower and "pni" not in txt_lower):
            return 0.8
        if "fr" in txt_lower or "respiracao" in txt_lower:
            return 3.0
        if "bpm" in txt_lower or "frequencia" in txt_lower or "pni" in txt_lower or "sistolica" in txt_lower or "diastolica" in txt_lower:
            return 5.0
        if ponto_num <= 100 and "bpm" not in txt_lower:
            return abs(ponto_num) * (3.0 / 100.0)
        else:
            return 5.0

    return None


def avaliar_pontos(pontos, equipamento):
    for ponto in pontos:
        limite = obter_limite(equipamento, ponto.get("Ponto / referência", ""), ponto.get("Grandeza", ""))
        ponto["Limite RQ"] = limite
        valor = ponto.get("|Erro| + |Incerteza|")
        if limite is None or valor is None:
            ponto["Resultado"] = "PENDENTE"
        elif valor <= limite:
            ponto["Resultado"] = "APROVADO"
        else:
            ponto["Resultado"] = "REPROVADO"
    return pontos


def calcular_status_geral(pontos, equipamento):
    if not pontos:
        return "PENDENTE — nenhum ponto foi extraído"
    resultados = [p.get("Resultado") for p in pontos]
    if any(r == "REPROVADO" for r in resultados):
        return "REPROVADO — pelo menos um ponto excedeu o limite configurado"
    if all(r == "APROVADO" for r in resultados):
        return "APROVADO — todos os pontos estão dentro dos limites configurados"
    return "PENDENTE — existem pontos sem limite oficial configurado"


def extrair_pontos(tabelas_df, equipamento, texto_pdf=""):
    pontos = []
    
    for df in tabelas_df:
        col_erro, col_inc, col_ponto = localizar_colunas_resultado(df)
        if col_erro is None or col_inc is None:
            continue
            
        grandeza_atual = "Parâmetro Geral"
        for idx, row in df.iterrows():
            texto_linha = " ".join([str(val) for val in row.values if val])
            t_norm = normalizar(texto_linha)
            
            if "frequencia cardiaca" in t_norm or "oximetria" in t_norm:
                grandeza_atual = "Frequência Cardíaca da Oximetria"
            elif "saturacao" in t_norm or "spo2" in t_norm:
                grandeza_atual = "Saturação do Oxigênio no Sangue [SpO2]"
            elif "temperatura" in t_norm:
                grandeza_atual = "Temperatura"
            elif "pressao" in t_norm or "pni" in t_norm:
                grandeza_atual = "Pressão Arterial (PNI)"

            erro = numero_ptbr(row.get(col_erro))
            incerteza = numero_ptbr(row.get(col_inc))
            if erro is None or incerteza is None:
                continue
                
            ponto = str(row.get(col_ponto, "")).strip() if row.get(col_ponto) is not None else ""
            if ponto.lower() == "nan":
                ponto = ""
                
            pontos.append({
                "ID": len(pontos) + 1,
                "Grandeza": grandeza_atual,
                "Tabela PDF": df.attrs.get("numero_tabela_pdf", ""),
                "Ponto / referência": ponto,
                "Erro lido": erro,
                "Incerteza lida": abs(incerteza),
                "|Erro| + |Incerteza|": abs(erro) + abs(incerteza),
                "Limite RQ": None,
                "Resultado": "PENDENTE",
            })
            
    if pontos and all(p["Grandeza"] == "Parâmetro Geral" for p in pontos):
        metade = len(pontos) // 2
        for i, p in enumerate(pontos):
            p["Grandeza"] = "Frequência Cardíaca da Oximetria" if i < metade else "Saturação do Oxigênio no Sangue [SpO2]"

    return avaliar_pontos(pontos, equipamento)


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
            "Limite RQ", "Resultado",
        ]]
        for p in pontos:
            dados_p.append([
                escape(str(p.get("Grandeza", ""))[:30]),
                escape(str(p.get("Ponto / referência", ""))[:20]),
                fmt_num(p.get("Erro lido")),
                fmt_num(p.get("Incerteza lida")),
                fmt_num(p.get("|Erro| + |Incerteza|")),
                fmt_num(p.get("Limite RQ")),
                escape(str(p.get("Resultado", ""))),
            ])
        tabp = Table(dados_p, colWidths=[130, 70, 50, 60, 90, 65, 80], repeatRows=1)
        tabp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        conteudo.append(tabp)
    else:
        conteudo.append(Paragraph(
            "Nenhum ponto com erro e incerteza foi identificado automaticamente.",
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
    "O sistema valida os certificados comparando |erro| + |incerteza| com os limites oficiais "
    "(Frequência Cardíaca fixa em 5 e Saturação em 3%)."
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
            metadados = extrair_metadados(texto, pdf_file.name)
            equipamento = metadados.get("Equipamento identificado", "")
            pontos = extrair_pontos(tabelas_pdf_para_df(tabelas), equipamento, texto)

            st.write("**Dados identificados no certificado**")
            st.json(metadados)

            if equipamento == "Não identificado com segurança":
                st.warning("Não consegui identificar o equipamento com segurança.")
            else:
                st.info(f"Equipamento identificado: **{equipamento}**")

            if pontos:
                st.write("**Pontos extraídos e cálculos dinâmicos**")
                # Remove colunas desnecessárias para exibição limpa
                df_exibicao = pd.DataFrame(pontos).drop(columns=["ID", "Tabela PDF"], errors="ignore")
                st.dataframe(df_exibicao, use_container_width=True)
            else:
                st.warning("Não encontrei uma tabela com colunas reconhecíveis.")

            status_geral = calcular_status_geral(pontos, equipamento)
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
                st.info("A liberação exige aprovação de todos os pontos, nome do técnico e OS.")

            observacao = "Validação aplicada com limite fixo de 5 para FC e 3% para SpO2."
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
st.caption("Validador de Certificados de Calibração.")