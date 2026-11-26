import json
import re
from pathlib import Path
import pandas as pd


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
        "₂": "2", "₀": "0",
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


def carregar_regras(caminho="regras_rq111.json"):
    arq = Path(caminho)
    if not arq.exists():
        raise FileNotFoundError(f"Arquivo de regras não encontrado: {caminho}")
    with open(arq, "r", encoding="utf-8") as f:
        return json.load(f)


def _obter_parametros_equipamento(equipamento, regras):
    config_eq = regras.get(equipamento)
    if not config_eq:
        return []

    parametros = list(config_eq.get("parametros", []))
    base_monitor = config_eq.get("herdar_monitor_de")
    if base_monitor and base_monitor in regras:
        existentes = {normalizar(p.get("grandeza", "")) for p in parametros}
        for p_base in regras[base_monitor].get("parametros", []):
            if normalizar(p_base.get("grandeza", "")) not in existentes:
                parametros.append(p_base)
    return parametros


def _extrair_bloco_instrumento(texto):
    """Isola apenas a seção 'DADOS DO INSTRUMENTO' para não confundir com 'CONDIÇÕES AMBIENTAIS'."""
    m = re.search(
        r"dados\s+do\s+instrumento(.*?)(?:3\s*\.\s*condi|condicoes\s+ambientais|procedimento\s+de\s+calibracao|padrao\(oes\))",
        normalizar(texto),
        flags=re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return normalizar(texto[:900])


def identificar_equipamento_dinamico(texto, nome_arquivo, regras, tipo_manual="Automático"):
    if tipo_manual and tipo_manual != "Automático":
        return tipo_manual

    texto_norm = normalizar(texto)
    bloco_inst = _extrair_bloco_instrumento(texto)
    alvo_principal = normalizar(f"{nome_arquivo} {bloco_inst}")

    # Extrai apenas a seção de resultados para checar pontos medidos sem pegar condições ambientais
    m_res = re.search(r"resultados\s+da\s+calibracao(.*)", texto_norm, flags=re.DOTALL)
    texto_resultados = m_res.group(1) if m_res else texto_norm

    m_cap = re.search(r"capacidade\s*maxima\s*[:\-]?\s*([\d,\.]+)\s*(kg|g)\b", texto_norm)
    cap_kg = None
    if m_cap:
        val_cap = numero_ptbr(m_cap.group(1))
        unid_cap = m_cap.group(2)
        if val_cap is not None:
            cap_kg = val_cap / 1000.0 if unid_cap == "g" else val_cap

    if "balanca" in alvo_principal:
        if "analitica" in alvo_principal and "Balança analítica - Área de processamento" in regras:
            return "Balança analítica - Área de processamento"
        if (
            "neonatal" in alvo_principal
            or "pediatrica" in alvo_principal
            or (cap_kg is not None and cap_kg <= 30)
        ) and "Balança digital - Neonatal" in regras:
            return "Balança digital - Neonatal"
        if (cap_kg is not None and cap_kg >= 500) and "Balança plataforma 500Kg" in regras:
            return "Balança plataforma 500Kg"
        if "Balança digital e bioimpedância - Adultos" in regras:
            return "Balança digital e bioimpedância - Adultos"

    modelos_especificos = [
        (["zoll", "m2"], "Desfibrilador - ZOLL M2"),
        (["mindray", "beneheart", "d3"], "Desfibrilador - MINDRAY BeneHeart D3"),
        (["philips", "dfm100", "dfm 100"], "Desfibrilador - PHILIPS DFM100"),
        (["instramed", "cardiomax"], "Desfibrilador - INSTRAMED Cardiomax"),
        (["nihon", "kohden"], "Desfibrilador DEA - NIHON KOHDEN"),
    ]
    for chaves, eq_nome in modelos_especificos:
        if eq_nome in regras and any(c in alvo_principal for c in chaves):
            return eq_nome

    # Diferenciação específica para Termômetros e Termohigrômetros (usando apenas o bloco do instrumento)
    if "termometro" in alvo_principal or "termohigrometro" in alvo_principal:
        if "infravermelho" in alvo_principal:
            if (
                re.search(r"(?<![\d,\.])(?:36|38|40)(?:[,\.]0+)?\b", texto_resultados)
                and not re.search(r"(?<![\d,\.])(?:2|5|8|15|20)(?:[,\.]0+)?\b", texto_resultados)
                and "Termômetro infravermelho - Paciente" in regras
            ):
                return "Termômetro infravermelho - Paciente"
            if "Termômetro infravermelho - Maletas (amostras e medicamentos)" in regras:
                return "Termômetro infravermelho - Maletas (amostras e medicamentos)"

        if "freezer" in alvo_principal or re.search(r"-\s*(?:5|10|20)(?:[,\.]\d+)?\b", texto_resultados):
            if "Termômetro ou Termohigrômetro - Freezer" in regras:
                return "Termômetro ou Termohigrômetro - Freezer"

        if "geladeira" in alvo_principal or "frigobar" in alvo_principal:
            if "Termômetro ou Termohigrômetro - Geladeira e/ou Frigobar" in regras:
                return "Termômetro ou Termohigrômetro - Geladeira e/ou Frigobar"

        if "termohigrometro" in alvo_principal or "ambiente" in alvo_principal or "%ur" in texto_resultados or "umidade" in texto_resultados:
            if "Termohigrômetro - Temperatura Ambiente" in regras:
                return "Termohigrômetro - Temperatura Ambiente"

        if "Termômetro ou Termohigrômetro - Geladeira e/ou Frigobar" in regras:
            return "Termômetro ou Termohigrômetro - Geladeira e/ou Frigobar"

    melhor_eq = None
    melhor_score = 0

    for eq_nome, dados in regras.items():
        palavras = [normalizar(p) for p in dados.get("palavras_chave", []) if p]
        score = sum(1 for p in palavras if p in alvo_principal)
        if score > melhor_score:
            melhor_score = score
            melhor_eq = eq_nome

    if melhor_eq and melhor_score > 0:
        return melhor_eq

    return next(iter(regras.keys()), "Não identificado")


def _linha_bate_chave(texto_norm, chaves):
    for k in chaves:
        if not k:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", texto_norm):
            return True
    return False


def _selecionar_parametro(parametros, linha_norm, contexto_norm, contexto_pressao):
    if len(parametros) == 1:
        return parametros[0]

    # 1. Unidade direta no início da linha da tabela
    mapa_unidades_inicio = [
        (r"^j\s+[\d,\.\-−]", "energia"),
        (r"^%spo2\s+[\d,\.\-−]", "oximetria"),
        (r"^bpm\s+[\d,\.\-−]", "frequencia cardiaca"),
        (r"^(?:brpm|rpm)\s+[\d,\.\-−]", "respiracao"),
        (r"^(?:°c|oc|c)\s+[\d,\.\-−]", "temperatura"),
        (r"^(?:%ur|%rh|ur|rh)\s+[\d,\.\-−]", "umidade"),
    ]
    for padrao_unid, alvo_grandeza in mapa_unidades_inicio:
        if re.match(padrao_unid, linha_norm):
            for param in parametros:
                if alvo_grandeza in normalizar(param.get("grandeza", "")):
                    return param

    # Caso especial de "%" sozinho no início da linha: pode ser Umidade ou Oximetria (SpO2)
    if re.match(r"^%\s+[\d,\.\-−]", linha_norm):
        for param in parametros:
            g_norm = normalizar(param.get("grandeza", ""))
            if "umidade" in g_norm:
                return param
        for param in parametros:
            g_norm = normalizar(param.get("grandeza", ""))
            if "oximetria" in g_norm:
                return param

    # 2. Pressão Não Invasiva (mmHg): usa o subtítulo ativo (Sistólica / Diastólica / Média)
    if re.match(r"^mmhg\s+[\d,\.\-−]", linha_norm):
        alvo_p = contexto_pressao or "sistolica"
        for param in parametros:
            g_norm = normalizar(param.get("grandeza", ""))
            if "pressao" in g_norm and alvo_p in g_norm:
                return param
        nomes_p = {
            "sistolica": "Pressão Não Invasiva - Sistólica",
            "diastolica": "Pressão Não Invasiva - Diastólica",
            "media": "Pressão Não Invasiva - Média",
        }
        return {
            "grandeza": nomes_p.get(alvo_p, "Pressão Não Invasiva"),
            "unidade": "mmHg",
            "desvio_padrao": 5.0,
            "tipo_desvio_padrao": "fixo",
            "pontos": [],
        }

    # 3. Palavra-chave exata na própria linha
    for param in parametros:
        chaves = [normalizar(k) for k in param.get("palavras_grandeza", [])]
        if _linha_bate_chave(linha_norm, chaves):
            return param

    # 4. Palavra-chave exata no cabeçalho da seção/tabela ativa
    for param in parametros:
        chaves = [normalizar(k) for k in param.get("palavras_grandeza", [])]
        if _linha_bate_chave(contexto_norm, chaves):
            return param

    return None


def _buscar_ou_calcular_regra_ponto(param, valor_referencia):
    pontos_config = param.get("pontos", [])
    for item in pontos_config:
        p = float(item["ponto"])
        if abs(valor_referencia - p) <= max(0.05, abs(p) * 0.005):
            return item, False

    desvio_padrao = float(param.get("desvio_padrao", 0.0))
    tipo_padrao = param.get("tipo_desvio_padrao", "fixo")

    if "energia" in normalizar(param.get("grandeza", "")) and valor_referencia < 20:
        tol = max(3.0, round(abs(valor_referencia) * (desvio_padrao / 100.0), 4))
        return {
            "ponto": valor_referencia,
            "desvio": tol,
            "tipo_desvio": "fixo",
            "min": round(valor_referencia - tol, 4),
            "max": round(valor_referencia + tol, 4),
        }, True

    if tipo_padrao == "percentual":
        tol = round(abs(valor_referencia) * (desvio_padrao / 100.0), 4)
    else:
        tol = desvio_padrao

    return {
        "ponto": valor_referencia,
        "desvio": desvio_padrao,
        "tipo_desvio": tipo_padrao,
        "min": round(valor_referencia - tol, 4),
        "max": round(valor_referencia + tol, 4),
    }, True


def validar_pontos_dinamico(texto_pdf, equipamento, regras):
    parametros = _obter_parametros_equipamento(equipamento, regras)
    if not parametros:
        return []

    texto_total_norm = normalizar(texto_pdf)
    pos_padrao = texto_total_norm.find("indicado no padrao")
    pos_instrumento = texto_total_norm.find("indicado no instrumento")
    padrao_antes_instrumento = (
        pos_padrao != -1
        and pos_instrumento != -1
        and pos_padrao < pos_instrumento
        and "valor indicado no padrao valor indicado no instrumento" not in texto_total_norm
    )

    pontos_extraidos = []
    linhas = texto_pdf.splitlines()
    capturando_tabela = False
    contexto_grandeza = ""
    contexto_pressao = ""

    for linha in linhas:
        l_low = linha.lower().strip()
        linha_norm = normalizar(linha)

        if not l_low:
            continue

        if any(amb in l_low for amb in [
            "temperatura do ar",
            "umidade relativa",
            "pressão atmosférica",
            "pressao atmosferica",
            "hpa",
        ]):
            continue

        if any(fim in l_low for fim in [
            "condições ambientais",
            "condicoes ambientais",
            "ensaio de excentricidade",
            "curva de calibração",
            "curva de calibracao",
            "***** fim",
            "observações",
            "observacoes",
            "legendas para interpretação",
            "legendas para interpretacao",
        ]):
            capturando_tabela = False
            continue

        if (
            "resultados da calibração" in l_low
            or "resultados da calibracao" in l_low
            or ("valor indicado" in l_low and ("padrão" in l_low or "padrao" in l_low or "instrumento" in l_low))
            or ("incerteza" in l_low and "erro" in l_low)
        ):
            capturando_tabela = True
            continue

        if not capturando_tabela:
            continue

        # Detecta os subtítulos de pressão imediatamente antes de qualquer filtro
        if "sistolica" in linha_norm:
            contexto_pressao = "sistolica"
            contexto_grandeza = linha_norm
            continue
        if "diastolica" in linha_norm:
            contexto_pressao = "diastolica"
            contexto_grandeza = linha_norm
            continue
        if "pressao media" in linha_norm or "pni media" in linha_norm:
            contexto_pressao = "media"
            contexto_grandeza = linha_norm
            continue

        if any(spec in l_low for spec in [
            "carga mínima",
            "carga minima",
            "capacidade máxima",
            "capacidade maxima",
            "resolução",
            "resolucao",
            "fator de abrangência",
            "fator de abrangencia",
            "grau de liberdade",
            "valor indicado",
            "incerteza de medição",
            "incerteza de medicao",
            "valor de uma divis",
        ]):
            continue

        linha_sem_siglas = re.sub(r"\b(spo2|etco2|co2|m2|d3|dfm100)\b", " ", linha_norm)
        match_nums = re.findall(r"([−\-\d,\.]+)", linha_sem_siglas)

        if len(match_nums) < 4:
            if any(w in linha_norm for w in [
                "frequencia cardiaca", "oximetria", "spo2",
                "respiratoria", "respiracao", "capnografia",
                "etco2", "energia", "temperatura", "umidade"
            ]):
                contexto_grandeza = linha_norm
            else:
                for p in parametros:
                    chaves_p = [normalizar(k) for k in p.get("palavras_grandeza", [])]
                    if _linha_bate_chave(linha_norm, chaves_p):
                        contexto_grandeza = linha_norm
                        break
            continue

        if "/" in linha or re.search(r"\b20[2-3]\d\b", linha):
            continue

        val1 = numero_ptbr(match_nums[0])
        val2 = numero_ptbr(match_nums[1])
        erro_val = numero_ptbr(match_nums[2])
        inc_val = numero_ptbr(match_nums[3])

        if val1 is None or val2 is None or inc_val is None:
            continue

        param = _selecionar_parametro(parametros, linha_norm, contexto_grandeza, contexto_pressao)
        if not param:
            continue

        if padrao_antes_instrumento:
            ponto_nominal = val2
            ponto_lido = val1
        elif "energia" in normalizar(param.get("grandeza", "")) and (val2 % 5 == 0 and val1 % 5 != 0):
            ponto_nominal = val2
            ponto_lido = val1
        else:
            ponto_nominal = val1
            ponto_lido = val2

        regra_ponto, ponto_antigo = _buscar_ou_calcular_regra_ponto(param, ponto_nominal)
        if not regra_ponto:
            continue

        desvio_cfg = float(regra_ponto["desvio"])
        if regra_ponto.get("tipo_desvio") == "percentual":
            tolerancia = abs(ponto_nominal) * (desvio_cfg / 100.0)
        else:
            tolerancia = desvio_cfg

        lim_min = regra_ponto.get("min")
        lim_max = regra_ponto.get("max")

        erro_real = erro_val if erro_val is not None else (ponto_lido - ponto_nominal)
        erro_total = abs(erro_real) + abs(inc_val)

        dentro_tolerancia = erro_total <= (tolerancia + 1e-6)
        dentro_limites = True
        if lim_min is not None and lim_max is not None:
            dentro_limites = ((float(lim_min) - 0.05) <= ponto_lido <= (float(lim_max) + 0.05))

        aprovado = dentro_tolerancia and dentro_limites

        item = {
            "Grandeza": param.get("grandeza", ""),
            "Unidade": param.get("unidade", ""),
            "Ponto Nominal": fmt_num(ponto_nominal),
            "Ponto Lido": fmt_num(ponto_lido),
            "Limite Mínimo": fmt_num(lim_min) if lim_min is not None else "-",
            "Limite Máximo": fmt_num(lim_max) if lim_max is not None else "-",
            "Erro": erro_real,
            "Incerteza": abs(inc_val),
            "Erro Total": erro_total,
            "Desvio Aceitável": tolerancia,
            "Regra": "Ponto antigo (calculado)" if ponto_antigo else "RQ.COR.111",
            "CONCLUSAO": "Aprovado" if aprovado else "Reprovado",
        }

        if item not in pontos_extraidos:
            pontos_extraidos.append(item)

    return pontos_extraidos