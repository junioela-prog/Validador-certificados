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


def identificar_equipamento_dinamico(texto, nome_arquivo, regras, tipo_manual="Automático"):
    if tipo_manual and tipo_manual != "Automático":
        return tipo_manual

    texto_norm = normalizar(texto)
    alvo = normalizar(f"{nome_arquivo} {texto[:3000]}")

    m_cap = re.search(r"capacidade\s*maxima\s*[:\-]?\s*([\d,\.]+)\s*(kg|g)\b", texto_norm)
    cap_kg = None
    if m_cap:
        val_cap = numero_ptbr(m_cap.group(1))
        unid_cap = m_cap.group(2)
        if val_cap is not None:
            cap_kg = val_cap / 1000.0 if unid_cap == "g" else val_cap

    if "balanca" in alvo:
        if "analitica" in alvo and "Balança analítica - Área de processamento" in regras:
            return "Balança analítica - Área de processamento"
        if (
            "neonatal" in alvo
            or "pediatrica" in alvo
            or (cap_kg is not None and cap_kg <= 30)
        ) and "Balança digital - Neonatal" in regras:
            return "Balança digital - Neonatal"
        if (cap_kg is not None and cap_kg >= 500) and "Balança plataforma 500Kg" in regras:
            return "Balança plataforma 500Kg"
        if "Balança digital e bioimpedância - Adultos" in regras:
            return "Balança digital e bioimpedância - Adultos"

    melhor_eq = None
    melhor_score = 0

    for eq_nome, dados in regras.items():
        palavras = [normalizar(p) for p in dados.get("palavras_chave", []) if p]
        score = sum(1 for p in palavras if p in alvo)
        if score > melhor_score:
            melhor_score = score
            melhor_eq = eq_nome

    if melhor_eq and melhor_score > 0:
        return melhor_eq

    return next(iter(regras.keys()), "Não identificado")


def _selecionar_parametro(parametros, linha_norm, contexto_norm):
    if len(parametros) == 1:
        return parametros[0]

    for param in parametros:
        chaves = [normalizar(k) for k in param.get("palavras_grandeza", [])]
        if any(k and k in linha_norm for k in chaves):
            return param

    for param in parametros:
        chaves = [normalizar(k) for k in param.get("palavras_grandeza", [])]
        if any(k and k in contexto_norm for k in chaves):
            return param

    return None


def _buscar_regra_ponto(pontos_config, valor_referencia):
    if not pontos_config:
        return None

    for item in pontos_config:
        p = float(item["ponto"])
        if abs(valor_referencia - p) <= max(0.01, p * 0.01):
            return item

    return min(pontos_config, key=lambda x: abs(float(x["ponto"]) - valor_referencia))


def validar_pontos_dinamico(texto_pdf, equipamento, regras):
    config_eq = regras.get(equipamento)
    if not config_eq:
        return []

    parametros = config_eq.get("parametros", [])
    todas_chaves_grandezas = [
        normalizar(k)
        for p in parametros
        for k in p.get("palavras_grandeza", [])
        if k
    ]

    pontos_extraidos = []
    linhas = texto_pdf.splitlines()
    capturando_tabela = False
    contexto_grandeza = ""

    for linha in linhas:
        l_low = linha.lower().strip()
        linha_norm = normalizar(linha)

        if not l_low:
            continue

        # Bloqueia explicitamente linhas ambientais e unidades de ambiente
        if any(amb in l_low for amb in [
            "temperatura do ar",
            "umidade relativa",
            "pressão atmosférica",
            "pressao atmosferica",
            "%ur",
            "hpa",
            "°c",
            "ºc",
        ]):
            continue

        # Desliga captura fora da tabela principal de resultados
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

        # Liga captura apenas na tabela de resultados da calibração
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

        if any(k in linha_norm for k in todas_chaves_grandezas):
            contexto_grandeza = linha_norm

        if "/" in linha or re.search(r"\b20[2-3]\d\b", linha):
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
        ]):
            continue

        match_nums = re.findall(r"([−\-\d,\.]+)", linha)
        if len(match_nums) < 4:
            continue

        val1 = numero_ptbr(match_nums[0])
        val2 = numero_ptbr(match_nums[1])
        erro_val = numero_ptbr(match_nums[2])
        inc_val = numero_ptbr(match_nums[3])

        if val1 is None or val2 is None or inc_val is None:
            continue

        param = _selecionar_parametro(parametros, linha_norm, contexto_grandeza)
        if not param:
            continue

        if "energia" in normalizar(param.get("grandeza", "")):
            ponto_nominal = val2
            ponto_lido = val1
        else:
            ponto_nominal = val1
            ponto_lido = val2

        regra_ponto = _buscar_regra_ponto(param.get("pontos", []), ponto_nominal)
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

        dentro_tolerancia = erro_total <= tolerancia
        dentro_limites = True
        if lim_min is not None and lim_max is not None:
            dentro_limites = (float(lim_min) <= ponto_lido <= float(lim_max))

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
            "CONCLUSAO": "Aprovado" if aprovado else "Reprovado",
        }

        if item not in pontos_extraidos:
            pontos_extraidos.append(item)

    return pontos_extraidos