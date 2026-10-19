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
    texto = texto.replace("º", "o").replace("ª", "a")
    texto = texto.replace("µ", "u").replace("μ", "u")
    texto = re.sub(r"[^a-z0-9,./%°+-]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def numero_ptbr(valor):
    """Converte números no padrão brasileiro e internacional."""
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
    s = re.sub(r"[^0-9,\.eE+-]", "", s)
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


def fmt_num(n):
    if n is None:
        return "Não identificado"
    return f"{n:.8g}".replace(".", ",")


def chave_ponto(valor):
    """Normaliza um ponto para comparar, por exemplo, '30' com '30,0'."""
    n = numero_ptbr(valor)
    if n is not None:
        return f"{n:.10g}"
    return normalizar(valor)


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


def extrair_metadados(texto):
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    dados = {}
    padroes = {
        "Cliente": r"(?:cliente|contratante)\s*[:\-]?\s*(.+)",
        "CNPJ": r"CNPJ\s*[:\-]?\s*([\d./-]+)",
        "Equipamento": r"(?:equipamento|instrumento|item calibrado)\s*[:\-]?\s*(.+)",
        "Modelo": r"modelo\s*[:\-]?\s*(.+)",
        "Fabricante": r"(?:fabricante|marca)\s*[:\-]?\s*(.+)",
        "Número de série": r"(?:número de série|nº série|n. série|serial)\s*[:\-]?\s*(.+)",
        "Patrimônio": r"(?:patrimônio|nº patrimônio)\s*[:\-]?\s*(.+)",
        "TAG": r"TAG\s*[:\-]?\s*(.+)",
        "Data da calibração": r"(?:data da calibração|data de calibração|data)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    }
    for nome, padrao in padroes.items():
        for linha in linhas:
            m = re.search(padrao, linha, re.IGNORECASE)
            if m:
                dados[nome] = m.group(1).strip()[:180]
                break
    return dados


def tabelas_pdf_para_df(tabelas):
    saida = []
    for num_tabela, tabela in enumerate(tabelas, start=1):
        if not tabela or len(tabela) < 2:
            continue
        linhas = [[(c or "").strip().replace("\n", " ") for c in linha] for linha in tabela]
        cab = []
        for i, c in enumerate(linhas[0]):
            nome = c or f"Coluna {i+1}"
            if nome in cab:
                nome = f"{nome} ({i+1})"
            cab.append(nome)
        try:
            df = pd.DataFrame(linhas[1:], columns=cab)
            if not df.empty:
                df.attrs["numero_tabela_pdf"] = num_tabela
                saida.append(df)
        except Exception:
            continue
    return saida


# ============================================================
# LEITURA DOS RESULTADOS DO CERTIFICADO PDF
# ============================================================

def localizar_colunas_resultado(df):
    nomes = {c: normalizar(c) for c in df.columns}

    col_erro = next(
        (c for c, n in nomes.items() if re.search(r"\berro\b", n)),
        None
    )
    col_inc = next(
        (c for c, n in nomes.items() if "incerteza" in n),
        None
    )

    # Procura coluna que identifica o ponto. Evita escolher "erro" e "incerteza".
    # Prefere o ponto nominal/referência ou o valor indicado pelo padrão.
    # Evita escolher o valor indicado pelo instrumento se houver coluna do padrão.
    termos_prioritarios = ("ponto", "referencia", "nominal", "setpoint", "valor indicado no padrao",
                           "valor indicado padrão", "valor do padrao", "indicacao do padrao")
    col_ponto = next(
        (c for c, n in nomes.items()
         if any(t in n for t in termos_prioritarios)
         and "erro" not in n and "incerteza" not in n),
        None
    )
    if col_ponto is None:
        termos_ponto = ("padrão", "padrao", "valor indicado", "indicado")
        col_ponto = next(
            (c for c, n in nomes.items()
             if any(t in n for t in termos_ponto)
             and "instrumento" not in n and "erro" not in n and "incerteza" not in n),
            None
        )
    return col_erro, col_inc, col_ponto


def extrair_pontos(tabelas_df):
    pontos = []
    for df in tabelas_df:
        col_erro, col_inc, col_ponto = localizar_colunas_resultado(df)
        if not col_erro or not col_inc:
            continue

        for idx, row in df.iterrows():
            erro = numero_ptbr(row.get(col_erro))
            incerteza = numero_ptbr(row.get(col_inc))
            if erro is None or incerteza is None:
                continue

            ponto = str(row.get(col_ponto, "")).strip() if col_ponto else ""
            if not ponto or ponto.lower() == "nan":
                ponto = f"Linha {idx + 2}"

            pontos.append({
                "ID": len(pontos) + 1,
                "Tabela PDF": df.attrs.get("numero_tabela_pdf", ""),
                "Ponto / referência": ponto,
                "Erro lido": erro,
                "Incerteza lida": abs(incerteza),
                "|Erro| + |Incerteza|": abs(erro) + abs(incerteza),
                "Limite permissível": None,
                "Origem do limite": "",
                "Resultado": "PENDENTE",
                "Motivo": "Ainda não foi localizado um limite correspondente na planilha."
            })
    return pontos


# ============================================================
# LEITURA AUTOMÁTICA DA PLANILHA RQ.COR.111
# ============================================================

def ler_excel(arquivo):
    arquivo.seek(0)
    return pd.read_excel(arquivo, sheet_name=None, header=None, dtype=object)


def encontrar_linha_cabecalho(df, termos, max_linhas=40):
    """Escolhe a linha com maior probabilidade de conter os títulos de ponto e limite."""
    melhor_linha, melhor_pontuacao = None, 0
    for i in range(min(len(df), max_linhas)):
        celulas = [normalizar(v) for v in df.iloc[i].tolist()]
        texto_linha = " ".join(c for c in celulas if c)
        tem_ponto = any(t in texto_linha for t in (
            "ponto", "nominal", "referencia", "referência", "faixa", "setpoint", "valor de calibracao"
        ))
        tem_limite = any(t in texto_linha for t in (
            "limite", "tolerancia", "tolerância", "permissivel", "permissível",
            "desvio aceitavel", "desvio aceitável", "desvio maximo", "desvio máximo",
            "erro maximo", "erro máximo", "erro permitido", "erro admissivel",
            "erro admissível", "exatidao", "exatidão", "mpe", "emp", "accuracy"
        ))
        pontuacao = sum(1 for c in celulas if any(t in c for t in termos))
        if tem_ponto:
            pontuacao += 3
        if tem_limite:
            pontuacao += 3
        if tem_ponto and tem_limite and pontuacao > melhor_pontuacao:
            melhor_linha, melhor_pontuacao = i, pontuacao
    return melhor_linha


def identificar_colunas_planilha(df):
    """Reconhece nomes comuns de ponto de calibração e limite/desvio aceitável."""
    termos = [
        "ponto", "nominal", "referencia", "erro", "limite", "tolerancia",
        "permissivel", "incerteza", "faixa", "desvio", "aceitavel", "maximo",
        "admissivel", "exatidao", "mpe", "emp", "accuracy"
    ]
    linha_cab = encontrar_linha_cabecalho(df, termos)
    if linha_cab is None:
        return None

    cabecalhos = []
    for j, valor in enumerate(df.iloc[linha_cab].tolist()):
        texto = str(valor).strip() if pd.notna(valor) else ""
        cabecalhos.append(normalizar(texto) or f"coluna {j+1}")

    termos_ponto = (
        "ponto", "valor nominal", "referencia", "nominal", "faixa",
        "setpoint", "ponto de calibracao", "valor de calibracao", "grandeza"
    )
    termos_limite = (
        "limite permissivel", "limite permissivel", "erro permissivel", "erro maximo",
        "erro permitido", "erro admissivel", "tolerancia", "limite de erro", "limite",
        "tolerado", "desvio aceitavel", "desvio maximo", "desvio permitido",
        "desvio admissivel", "erro maximo permitido", "erro maximo admissivel",
        "exatidao", "mpe", "emp", "accuracy", "criterio de aceitacao"
    )

    col_ponto = None
    col_limite = None
    # Preferência por rótulos explícitos; não usa coluna de erro/resultado medido como limite.
    for j, nome in enumerate(cabecalhos):
        if col_ponto is None and any(t in nome for t in termos_ponto):
            if not any(t in nome for t in ("erro", "incerteza", "desvio", "limite", "tolerancia")):
                col_ponto = j
        eh_limite = any(t in nome for t in termos_limite)
        proibido = any(t in nome for t in (
            "incerteza", "observacao", "observacoes", "resultado", "erro encontrado",
            "erro medido", "erro calculado", "erro do instrumento", "desvio encontrado"
        ))
        if eh_limite and not proibido:
            # Rótulos de limite explícitos têm preferência sobre cabeçalhos genéricos.
            peso = 2 if any(t in nome for t in (
                "desvio aceitavel", "limite permissivel", "erro permissivel", "erro permitido",
                "erro maximo", "erro admissivel", "tolerancia", "criterio de aceitacao"
            )) else 1
            if col_limite is None:
                col_limite = j
                peso_limite = peso
            elif peso > peso_limite:
                col_limite = j
                peso_limite = peso

    # Evita considerar um cabeçalho de tabela de resultados como uma tabela de limites.
    return {
        "linha_cabecalho": linha_cab,
        "cabecalhos": cabecalhos,
        "col_ponto": col_ponto,
        "col_limite": col_limite
    }


def extrair_limites_aba(df, nome_aba):
    """Extrai pares ponto-limite reconhecidos; não escolhe colunas numéricas às cegas."""
    estrutura = identificar_colunas_planilha(df)
    if not estrutura:
        return [], "Não identifiquei uma linha que contenha cabeçalho de ponto e de limite/desvio aceitável."

    cp = estrutura["col_ponto"]
    cl = estrutura["col_limite"]
    if cp is None or cl is None:
        return [], (
            "Encontrei uma possível linha de cabeçalho, mas não consegui reconhecer com segurança "
            "a coluna do ponto e/ou a coluna do limite/desvio aceitável. Verifique os títulos da aba."
        )

    limites = []
    inicio = estrutura["linha_cabecalho"] + 1
    for i in range(inicio, len(df)):
        ponto = df.iat[i, cp] if cp < df.shape[1] else None
        limite_original = df.iat[i, cl] if cl < df.shape[1] else None
        n_ponto = numero_ptbr(ponto)
        n_limite = numero_ptbr(limite_original)
        if ponto is None or pd.isna(ponto) or n_ponto is None or n_limite is None:
            continue
        # A planilha pode mostrar limites como ±0,5 ou -0,5; o limite é uma magnitude positiva.
        limites.append({
            "ponto": str(ponto).strip(),
            "chave_ponto": chave_ponto(ponto),
            "limite": abs(n_limite),
            "aba": nome_aba,
            "linha": i + 1,
            "cabecalho_ponto": estrutura["cabecalhos"][cp],
            "cabecalho_limite": estrutura["cabecalhos"][cl],
        })

    if not limites:
        return [], (
            f"Reconheci as colunas '{estrutura['cabecalhos'][cp]}' e "
            f"'{estrutura['cabecalhos'][cl]}', mas não encontrei pares numéricos nas linhas abaixo."
        )
    return limites, ""

def termos_equipamento(metadados):
    termos = []
    for k in ("Equipamento", "Modelo", "Fabricante"):
        valor = metadados.get(k, "")
        if valor and len(normalizar(valor)) >= 3:
            termos.extend([x.strip() for x in re.split(r"[;,/|]", valor)
                           if len(normalizar(x)) >= 3])
    return list(dict.fromkeys(termos))


def sugerir_abas(excel_sheets, metadados):
    termos = [normalizar(t) for t in termos_equipamento(metadados)]
    pontuadas = []
    for nome, df in excel_sheets.items():
        nome_n = normalizar(nome)
        texto = " ".join(normalizar(v) for v in
                         df.fillna("").astype(str).values.flatten()[:3000])
        score = sum(3 for t in termos if t and t in nome_n)
        score += sum(1 for t in termos if t and t in texto)
        pontuadas.append((score, nome))
    pontuadas.sort(reverse=True)
    if not pontuadas or pontuadas[0][0] == 0:
        return list(excel_sheets.keys())
    maior = pontuadas[0][0]
    return [nome for score, nome in pontuadas if score == maior and score > 0]


def associar_limites(pontos, limites):
    """Associa pelo ponto numérico exato. Sem correspondência, fica pendente."""
    mapa = {}
    duplicados = set()
    for lim in limites:
        chave = lim["chave_ponto"]
        if chave in mapa:
            duplicados.add(chave)
        else:
            mapa[chave] = lim

    for p in pontos:
        chave = chave_ponto(p["Ponto / referência"])
        # Só faz associação automática por ponto numérico identificável.
        if numero_ptbr(p["Ponto / referência"]) is None:
            p["Resultado"] = "PENDENTE"
            p["Motivo"] = "O ponto do certificado não foi reconhecido como número para associação automática."
            continue
        if chave in duplicados:
            p["Resultado"] = "PENDENTE"
            p["Motivo"] = "Há pontos duplicados na planilha; confirme qual limite se aplica."
            continue
        lim = mapa.get(chave)
        if not lim:
            p["Resultado"] = "PENDENTE"
            p["Motivo"] = "Ponto não encontrado na aba selecionada da RQ.COR.111."
            continue

        p["Limite permissível"] = lim["limite"]
        p["Origem do limite"] = f"{lim['aba']} — linha {lim['linha']}"
        p["Resultado"] = (
            "APROVADO"
            if p["|Erro| + |Incerteza|"] <= lim["limite"]
            else "REPROVADO"
        )
        p["Motivo"] = (
            f"Soma {fmt_num(p['|Erro| + |Incerteza|'])}; "
            f"limite {fmt_num(lim['limite'])}; "
            f"fonte: aba {lim['aba']}, linha {lim['linha']}."
        )


# ============================================================
# RELATÓRIO PDF
# ============================================================

def gerar_relatorio_pdf(nome_usuario, numero_os, arquivo_nome, metadados,
                        pontos, status_geral, observacao, status_tecnico,
                        tecnico="", data_aprovacao=""):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24,
        topMargin=24, bottomMargin=24
    )
    estilos = getSampleStyleSheet()
    conteudo = [
        Paragraph("Relatório — Validador de Certificados", estilos["Title"]),
        Spacer(1, 8),
        Paragraph(f"<b>Técnico:</b> {escape(nome_usuario or 'Não informado')}", estilos["Normal"]),
        Paragraph(f"<b>Ordem de Serviço:</b> {escape(numero_os or 'Não informada')}", estilos["Normal"]),
        Paragraph(f"<b>Arquivo:</b> {escape(arquivo_nome)}", estilos["Normal"]),
        Paragraph(f"<b>Data de geração:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", estilos["Normal"]),
        Paragraph(f"<b>Resultado automático:</b> {escape(status_geral)}", estilos["Normal"]),
        Paragraph(f"<b>Decisão do técnico:</b> {escape(status_tecnico)}", estilos["Normal"]),
    ]
    if tecnico:
        conteudo.append(Paragraph(f"<b>Técnico que liberou:</b> {escape(tecnico)}", estilos["Normal"]))
    if data_aprovacao:
        conteudo.append(Paragraph(f"<b>Data/hora da liberação:</b> {escape(data_aprovacao)}", estilos["Normal"]))

    conteudo.extend([Spacer(1, 8), Paragraph("Dados identificados no certificado", estilos["Heading2"])])
    dados = [["Campo", "Valor"]]
    dados.extend([[escape(str(k)), escape(str(v))] for k, v in metadados.items()])
    if len(dados) == 1:
        dados.append(["Dados", "Nenhum campo foi identificado automaticamente."])
    tab = Table(dados, colWidths=[130, 450], repeatRows=1)
    tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    conteudo.append(tab)
    conteudo.extend([Spacer(1, 10), Paragraph("Pontos de medição e comparação", estilos["Heading2"])])

    if pontos:
        dados_p = [[
            "Ponto", "Erro", "Incerteza", "Soma |erro|+|inc|",
            "Limite RQ", "Resultado", "Origem"
        ]]
        for p in pontos:
            dados_p.append([
                escape(str(p.get("Ponto / referência", ""))[:25]),
                fmt_num(p.get("Erro lido")),
                fmt_num(p.get("Incerteza lida")),
                fmt_num(p.get("|Erro| + |Incerteza|")),
                fmt_num(p.get("Limite permissível")),
                escape(str(p.get("Resultado", ""))),
                escape(str(p.get("Origem do limite", "Não confirmado"))[:35]),
            ])
        tabp = Table(dados_p, colWidths=[80, 55, 65, 95, 60, 80, 115], repeatRows=1)
        tabp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        conteudo.append(tabp)
    else:
        conteudo.append(Paragraph("Nenhum ponto com erro e incerteza foi identificado.", estilos["Normal"]))

    conteudo.extend([
        Spacer(1, 10),
        Paragraph("Observação", estilos["Heading2"]),
        Paragraph(escape(observacao), estilos["Normal"]),
    ])
    doc.build(conteudo)
    buffer.seek(0)
    return buffer


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.title("📄 Validador de Certificados de Calibração")
st.write(
    "Envie a planilha RQ.COR.111 e os certificados. O sistema procura os pontos de calibração "
    "e os limites/desvios aceitáveis pelos cabeçalhos da planilha e compara |erro| + |incerteza| com o limite."
)

col1, col2 = st.columns(2)
with col1:
    nome_usuario = st.text_input("Nome do técnico responsável", placeholder="Digite seu nome")
with col2:
    numero_os = st.text_input("Número da Ordem de Serviço (OS)", placeholder="Ex.: OS-2026-00125")

rq_file = st.file_uploader("1. Envie a planilha RQ.COR.111 (.xlsx)", type=["xlsx"])
pdf_files = st.file_uploader(
    "2. Envie os certificados de calibração (.pdf)",
    type=["pdf"], accept_multiple_files=True
)

excel_sheets = None
if rq_file:
    try:
        excel_sheets = ler_excel(rq_file)
        st.success(f"Planilha carregada: {len(excel_sheets)} aba(s) encontrada(s).")
        with st.expander("Conferir conteúdo das abas da planilha"):
            for nome_aba, df in excel_sheets.items():
                st.write(f"**{nome_aba}** — {df.shape[0]} linhas × {df.shape[1]} colunas")
                st.dataframe(df.head(12), use_container_width=True)
                estrutura = identificar_colunas_planilha(df)
                if estrutura:
                    st.caption(
                        f"Cabeçalho provável na linha {estrutura['linha_cabecalho'] + 1}. "
                        f"Coluna do ponto: {estrutura['cabecalhos'][estrutura['col_ponto']] if estrutura['col_ponto'] is not None else 'não identificada'}. "
                        f"Coluna do limite: {estrutura['cabecalhos'][estrutura['col_limite']] if estrutura['col_limite'] is not None else 'não identificada'}."
                    )
                else:
                    st.caption("Cabeçalho de pontos/limites não reconhecido automaticamente nesta aba.")
    except Exception as e:
        st.error(f"Não foi possível ler a planilha. Confirme se é um arquivo .xlsx válido. Detalhe: {e}")
        excel_sheets = None

if pdf_files:
    for pdf_file in pdf_files:
        st.divider()
        st.subheader(f"Certificado: {pdf_file.name}")
        try:
            texto, tabelas = extrair_texto_pdf(pdf_file)
            metadados = extrair_metadados(texto)
            pontos = extrair_pontos(tabelas_pdf_para_df(tabelas))

            if metadados:
                st.write("**Dados identificados no certificado**")
                st.json(metadados)
            else:
                st.warning("Não consegui identificar os dados principais. O PDF pode ser digitalizado ou usar outros rótulos.")

            if pontos:
                st.write("**Pontos extraídos do certificado**")
                st.dataframe(pd.DataFrame(pontos), use_container_width=True)
            else:
                st.warning(
                    "Não encontrei tabela com colunas reconhecíveis de erro e incerteza. "
                    "Se o PDF for digitalizado, será necessário OCR; confira se o texto pode ser selecionado."
                )

            if excel_sheets and pontos:
                abas_sugeridas = sugerir_abas(excel_sheets, metadados)
                abas = list(excel_sheets.keys())
                aba_padrao = abas_sugeridas[0] if len(abas_sugeridas) == 1 else abas[0]
                aba_escolhida = st.selectbox(
                    "Aba da RQ.COR.111 para este equipamento",
                    abas,
                    index=abas.index(aba_padrao),
                    key=f"aba_{pdf_file.name}"
                )
                st.caption("Sugestão automática de aba: " + (", ".join(abas_sugeridas) if abas_sugeridas else "nenhuma"))

                limites, erro_leitura = extrair_limites_aba(excel_sheets[aba_escolhida], aba_escolhida)
                if limites:
                    associar_limites(pontos, limites)
                    st.success(f"Localizei {len(limites)} par(es) ponto/limite na aba {aba_escolhida}.")
                    st.caption(
                        f"Comparação usando: ponto = '{limites[0]['cabecalho_ponto']}' | "
                        f"limite = '{limites[0]['cabecalho_limite']}'. "
                        "Regra: módulo do erro + módulo da incerteza ≤ limite."
                    )
                else:
                    for p in pontos:
                        p["Resultado"] = "PENDENTE"
                        p["Motivo"] = erro_leitura
                    st.warning(
                        f"Não consegui extrair pontos e limites automaticamente desta aba: {erro_leitura} "
                        "Confira a prévia da planilha acima; não será escolhido um limite por adivinhação."
                    )
            else:
                for p in pontos:
                    p["Resultado"] = "PENDENTE"
                    p["Motivo"] = "Carregue a planilha RQ.COR.111 para comparar os limites."

            if not pontos:
                status_geral = "PENDENTE DE ANÁLISE"
            elif any(p["Resultado"] == "REPROVADO" for p in pontos):
                status_geral = "REPROVADO"
            elif all(p["Resultado"] == "APROVADO" for p in pontos):
                status_geral = "APROVADO"
            else:
                status_geral = "PENDENTE DE ANÁLISE"

            st.write("### Resultado automático")
            if status_geral == "APROVADO":
                st.success("APROVADO — todos os pontos encontrados foram comparados e estão dentro dos limites.")
            elif status_geral == "REPROVADO":
                st.error("REPROVADO — pelo menos um ponto ultrapassou o limite permissível.")
            else:
                st.warning("PENDENTE DE ANÁLISE — há pontos ou limites que não foram associados com segurança.")

            if pontos:
                st.dataframe(pd.DataFrame(pontos), use_container_width=True)

            chave = re.sub(r"[^A-Za-z0-9_-]", "_", pdf_file.name)
            chave_liberacao = f"liberacao_{chave}"
            chave_data = f"data_liberacao_{chave}"
            chave_tecnico_liberacao = f"tecnico_liberacao_{chave}"

            if chave_liberacao not in st.session_state:
                st.session_state[chave_liberacao] = False

            st.write("### Liberação técnica")
            pode_liberar = (
                status_geral == "APROVADO"
                and bool(nome_usuario.strip())
                and bool(numero_os.strip())
            )

            if status_geral != "APROVADO":
                st.info("A liberação fica bloqueada até todos os pontos serem aprovados.")
            elif not nome_usuario.strip() or not numero_os.strip():
                st.info("Preencha o nome do técnico e o número da OS para habilitar a liberação.")

            if st.button(
                "✅ Liberar equipamento",
                key=f"botao_liberar_{chave}",
                disabled=not pode_liberar
            ):
                st.session_state[chave_liberacao] = True
                st.session_state[chave_data] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                st.session_state[chave_tecnico_liberacao] = nome_usuario.strip()

            if st.session_state[chave_liberacao] and status_geral == "APROVADO":
                st.success(
                    f"Liberação registrada nesta sessão por {st.session_state.get(chave_tecnico_liberacao, nome_usuario)} "
                    f"em {st.session_state.get(chave_data, '')}."
                )
                status_tecnico = "LIBERADO PELO TÉCNICO"
                tecnico_pdf = st.session_state.get(chave_tecnico_liberacao, nome_usuario)
                data_pdf = st.session_state.get(chave_data, "")
            elif status_geral == "REPROVADO":
                status_tecnico, tecnico_pdf, data_pdf = "BLOQUEADO — resultado reprovado", "", ""
            elif status_geral != "APROVADO":
                status_tecnico, tecnico_pdf, data_pdf = "BLOQUEADO — análise pendente", "", ""
            else:
                status_tecnico, tecnico_pdf, data_pdf = "AGUARDANDO LIBERAÇÃO DO TÉCNICO", "", ""

            observacao = (
                "Regra aplicada: |erro| + |incerteza| <= limite permissível localizado na RQ.COR.111. "
                "A associação automática depende do reconhecimento correto dos cabeçalhos, pontos, "
                "unidades e limites da planilha e do certificado. Revise a correspondência antes de usar "
                "este relatório como registro técnico oficial."
            )
            relatorio = gerar_relatorio_pdf(
                nome_usuario, numero_os, pdf_file.name, metadados, pontos,
                status_geral, observacao, status_tecnico, tecnico_pdf, data_pdf
            )
            st.download_button(
                "📥 Baixar relatório PDF",
                data=relatorio,
                file_name=f"relatorio_{chave}.pdf",
                mime="application/pdf",
                key=f"relatorio_{chave}"
            )
        except Exception as e:
            st.error(f"Erro ao processar este certificado: {e}")

st.divider()
st.caption(
    "Versão de teste. A associação automática depende do formato real da RQ.COR.111 e das tabelas dos PDFs. "
    "Pontos sem correspondência inequívoca ficam pendentes; confira os resultados antes de qualquer liberação oficial."
)
