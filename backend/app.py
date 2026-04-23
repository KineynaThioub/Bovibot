"""
BoviBot — Backend FastAPI Complet
Gestion d'élevage bovin avec LLM + PL/SQL
Projet L3 — ESP/UCAD
"""
import os, re, json, httpx
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import mysql.connector
from datetime import date, datetime

app = FastAPI(title="BoviBot API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ───────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "bovibot"),
    "charset":  "utf8mb4",
}

LLM_API_KEY  = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")

LLM_FALLBACK_URL   = os.getenv("LLM_FALLBACK_URL", "")
LLM_FALLBACK_KEY   = os.getenv("LLM_FALLBACK_KEY", "ollama")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "mistral")

_TODAY = date.today().isoformat()

# ── System Prompt LLM ──────────────────────────────────────────
SYSTEM_PROMPT = f"""Tu es BoviBot, un assistant IA expert MySQL pour un élevage bovin au Sénégal.
Tu communiques en français. La date du jour est : {_TODAY}

═══════════════════════════════════════════════════════════════
RÈGLE ABSOLUE — FORMAT DE SORTIE
═══════════════════════════════════════════════════════════════
Réponds TOUJOURS et UNIQUEMENT avec un objet JSON valide.
Aucun texte avant, aucun texte après, pas de blocs ```json.
Un seul JSON par réponse. Violation = erreur critique en production.

═══════════════════════════════════════════════════════════════
SCHÉMA BASE DE DONNÉES MySQL 8 (seules tables/colonnes autorisées)
═══════════════════════════════════════════════════════════════

TABLE races
  id INT | nom VARCHAR(100) | origine VARCHAR(100)
  poids_adulte_moyen_kg DECIMAL(6,2) | production_lait_litre_jour DECIMAL(6,2)

TABLE animaux
  id INT | numero_tag VARCHAR(30) | nom VARCHAR(100) | race_id INT
  sexe ENUM('M','F') | date_naissance DATE | poids_actuel DECIMAL(6,2)
  statut ENUM('actif','vendu','mort','quarantaine') | mere_id INT | pere_id INT
  notes TEXT | created_at TIMESTAMP
  [race_id → races.id] [mere_id → animaux.id] [pere_id → animaux.id]

TABLE pesees
  id INT | animal_id INT | poids_kg DECIMAL(6,2) | date_pesee DATE
  agent VARCHAR(100) | notes TEXT | created_at TIMESTAMP
  [animal_id → animaux.id]

TABLE sante
  id INT | animal_id INT | type ENUM('vaccination','traitement','examen','chirurgie')
  description TEXT | date_acte DATE | veterinaire VARCHAR(100)
  medicament VARCHAR(200) | cout DECIMAL(10,2) | prochain_rdv DATE | created_at TIMESTAMP
  [animal_id → animaux.id]

TABLE reproduction
  id INT | mere_id INT | pere_id INT | date_saillie DATE
  date_velage_prevue DATE | date_velage_reelle DATE | nb_veaux INT
  statut ENUM('en_gestation','vele','avortement','echec') | notes TEXT
  [mere_id → animaux.id] [pere_id → animaux.id]

TABLE alimentation
  id INT | animal_id INT | type_aliment VARCHAR(100)
  quantite_kg DECIMAL(6,2) | date_alimentation DATE | cout_unitaire_kg DECIMAL(6,2)
  [animal_id → animaux.id]

TABLE ventes
  id INT | animal_id INT | acheteur VARCHAR(150) | telephone_acheteur VARCHAR(20)
  date_vente DATE | poids_vente_kg DECIMAL(6,2) | prix_fcfa DECIMAL(12,2)
  notes TEXT | created_at TIMESTAMP
  [animal_id → animaux.id]

TABLE alertes
  id INT | animal_id INT(nullable) | type ENUM('poids','vaccination','velage','sante','alimentation','autre')
  message TEXT | niveau ENUM('info','warning','critical')
  date_creation TIMESTAMP | traitee BOOLEAN
  [animal_id → animaux.id]

TABLE historique_statut
  id INT | animal_id INT | ancien_statut VARCHAR(20)
  nouveau_statut VARCHAR(20) | date_changement TIMESTAMP
  [animal_id → animaux.id]

FONCTIONS SQL (utiliser dès que pertinent)
  fn_age_en_mois(animal_id)  → INT           âge de l'animal en mois
  fn_gmq(animal_id)          → DECIMAL(6,3)  gain moyen quotidien en kg/jour

PROCÉDURES STOCKÉES (uniquement pour les actions)
  sp_enregistrer_pesee(animal_id, poids_kg, date, agent)
  sp_declarer_vente(animal_id, acheteur, telephone, prix_fcfa, poids_vente_kg, date_vente)
  Note : tu peux utiliser numero_tag à la place de animal_id, le système résoudra automatiquement.

═══════════════════════════════════════════════════════════════
RÈGLES SQL OBLIGATOIRES
═══════════════════════════════════════════════════════════════
1. INTERDIT : SELECT * — toujours lister les colonnes explicitement
2. OBLIGATOIRE : LIMIT 100 sur tout SELECT non agrégé (COUNT/SUM/AVG/MIN/MAX exemptés)
3. INTERDIT : DELETE, UPDATE, INSERT, DROP, TRUNCATE, ALTER, CREATE
4. OBLIGATOIRE : JOIN races r ON a.race_id = r.id quand le nom de race est affiché
5. OBLIGATOIRE : filtre statut = 'actif' par défaut sur animaux (sauf demande contraire)
6. VALEURS EXACTES statut : 'actif' | 'vendu' | 'mort' | 'quarantaine'
7. VALEURS EXACTES sexe : 'M' | 'F'
8. FORMAT dates : YYYY-MM-DD uniquement
9. UTILISER fn_age_en_mois() et fn_gmq() dans les SELECT sur animaux quand pertinent

═══════════════════════════════════════════════════════════════
FORMATS JSON DE SORTIE
═══════════════════════════════════════════════════════════════

Consultation SQL :
{{"type":"query","sql":"SELECT ...","explication":"..."}}

Action procédure stockée :
{{"type":"action","procedure":"sp_nom","params":{{"param1":valeur,...}},"explication":"...","confirmation":"Résumé clair de l'opération"}}

Information générale :
{{"type":"info","explication":"..."}}

═══════════════════════════════════════════════════════════════
EXEMPLES CORRECTS (référence obligatoire)
═══════════════════════════════════════════════════════════════

[1] Liste des animaux actifs
{{"type":"query","sql":"SELECT a.id, a.numero_tag, a.nom, r.nom AS race, a.sexe, fn_age_en_mois(a.id) AS age_mois, a.poids_actuel, a.statut FROM animaux a LEFT JOIN races r ON a.race_id = r.id WHERE a.statut = 'actif' ORDER BY a.numero_tag LIMIT 100","explication":"Voici la liste des animaux actifs avec race et âge."}}

[2] GMQ d'un animal par numéro de tag
{{"type":"query","sql":"SELECT a.numero_tag, a.nom, r.nom AS race, fn_gmq(a.id) AS gmq_kg_jour, a.poids_actuel, fn_age_en_mois(a.id) AS age_mois FROM animaux a LEFT JOIN races r ON a.race_id = r.id WHERE a.numero_tag = 'TAG-001'","explication":"Voici le gain moyen quotidien de l'animal TAG-001."}}

[3] Enregistrement d'une pesée
{{"type":"action","procedure":"sp_enregistrer_pesee","params":{{"numero_tag":"TAG-001","poids_kg":325.0,"date":"{_TODAY}","agent":"BoviBot"}},"explication":"Je vais enregistrer une pesée de 325 kg pour TAG-001.","confirmation":"Confirmer : pesée 325,0 kg pour TAG-001 le {_TODAY} ?"}}

[4] Vaches en gestation avec jours restants
{{"type":"query","sql":"SELECT a.numero_tag, a.nom, r.nom AS race, rep.date_saillie, rep.date_velage_prevue, DATEDIFF(rep.date_velage_prevue, CURDATE()) AS jours_restants FROM reproduction rep JOIN animaux a ON rep.mere_id = a.id LEFT JOIN races r ON a.race_id = r.id WHERE rep.statut = 'en_gestation' ORDER BY rep.date_velage_prevue ASC LIMIT 100","explication":"Voici les vaches en gestation avec leur date de vêlage prévue."}}

[5] Coût d'alimentation par animal
{{"type":"query","sql":"SELECT a.numero_tag, a.nom, SUM(al.quantite_kg * al.cout_unitaire_kg) AS cout_total_fcfa, COUNT(*) AS nb_repas, MAX(al.date_alimentation) AS dernier_repas FROM alimentation al JOIN animaux a ON al.animal_id = a.id GROUP BY a.id, a.numero_tag, a.nom ORDER BY cout_total_fcfa DESC LIMIT 100","explication":"Voici le coût d'alimentation total par animal."}}

═══════════════════════════════════════════════════════════════
CHECKLIST INTERNE (valider avant chaque réponse)
═══════════════════════════════════════════════════════════════
✓ Toutes les colonnes existent dans le schéma ci-dessus ?
✓ Tous les JOINs sont corrects (race_id → races.id) ?
✓ LIMIT 100 présent si SELECT non agrégé ?
✓ Aucun SELECT * ?
✓ Aucune opération d'écriture directe (INSERT/UPDATE/DELETE) ?
✓ Le JSON est syntaxiquement valide (accolades, guillemets, virgules) ?
✓ Aucun texte hors JSON ?
Si une vérification échoue → répondre avec type "info" et expliquer la limitation.
"""

# ── Connexion MySQL ─────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def execute_query(sql: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        # Sérialiser les dates
        result = []
        for row in rows:
            clean = {}
            for k, v in row.items():
                if isinstance(v, (date, datetime)):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = v
            result.append(clean)
        return result
    finally:
        cursor.close(); conn.close()

def call_procedure(name: str, params: dict):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Résolution numero_tag → animal_id si le LLM fournit le tag plutôt que l'ID
        if "numero_tag" in params and "animal_id" not in params:
            cursor.execute(
                "SELECT id FROM animaux WHERE numero_tag = %s AND statut = 'actif'",
                (params["numero_tag"],)
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(404, f"Animal '{params['numero_tag']}' introuvable ou non actif")
            params = dict(params)
            params["animal_id"] = row[0]

        if name == "sp_enregistrer_pesee":
            cursor.callproc("sp_enregistrer_pesee", [
                params["animal_id"], params["poids_kg"],
                params["date"], params.get("agent", "BoviBot")
            ])
        elif name == "sp_declarer_vente":
            cursor.callproc("sp_declarer_vente", [
                params["animal_id"], params["acheteur"],
                params.get("telephone", ""), params["prix_fcfa"],
                params.get("poids_vente_kg", 0), params["date_vente"]
            ])
        else:
            raise HTTPException(400, f"Procédure inconnue : {name}")
        conn.commit()
        return {"success": True}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cursor.close(); conn.close()

async def _call_llm_api(base_url: str, api_key: str, model: str, messages: list, timeout: int = 30) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, "temperature": 0.1},
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

async def ask_llm(question: str, history: list = None) -> dict:
    if history is None:
        history = []
    try:
        q = question.lower().strip()

        # Raccourcis hardcodés pour les questions les plus fréquentes
        if ("animaux actifs" in q or "liste les animaux" in q
                or "consulter animaux" in q or "liste animaux" in q):
            return {
                "type": "query",
                "sql": "SELECT a.id, a.numero_tag, a.nom, r.nom AS race, a.sexe, fn_age_en_mois(a.id) AS age_mois, a.poids_actuel, a.statut FROM animaux a LEFT JOIN races r ON a.race_id = r.id WHERE a.statut = 'actif' ORDER BY a.numero_tag LIMIT 100",
                "explication": "Voici la liste des animaux actifs avec leur race et leur âge."
            }

        if ("combien" in q or "nombre" in q):
            return {
                "type": "query",
                "sql": "SELECT COUNT(*) as total FROM animaux WHERE statut='actif'",
                "explication": "Voici le nombre d'animaux actifs."
            }

        if ("race" in q or "races" in q):
            return {
                "type": "query",
                "sql": "SELECT id, nom, origine, poids_adulte_moyen_kg, production_lait_litre_jour FROM races ORDER BY nom",
                "explication": "Voici les races disponibles dans l'élevage."
            }

        # Construction du contexte conversationnel
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history[-4:]:
            if "question" in h:
                messages.append({"role": "user", "content": h["question"]})
            if "answer" in h:
                messages.append({"role": "assistant", "content": h["answer"]})
        messages.append({"role": "user", "content": question})

        # Appel LLM — Groq (primaire) avec fallback Ollama
        content = None
        try:
            content = await _call_llm_api(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, messages, timeout=30)
        except Exception as primary_error:
            if LLM_FALLBACK_URL:
                content = await _call_llm_api(
                    LLM_FALLBACK_URL, LLM_FALLBACK_KEY, LLM_FALLBACK_MODEL,
                    messages, timeout=120
                )
            else:
                raise primary_error

        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return {"type": "info", "explication": content}

        return {"type": "info", "explication": content}

    except Exception as e:
        return {"type": "info", "explication": f"Je n'ai pas pu traiter cette demande : {str(e)}"}

# ── Modèles Pydantic ────────────────────────────────────────────
class ChatMessage(BaseModel):
    question: str
    history: list = []
    confirm_action: bool = False
    pending_action: dict = {}

class AnimalCreate(BaseModel):
    numero_tag: str
    nom: Optional[str] = None
    race_id: Optional[int] = None
    sexe: str
    date_naissance: str
    poids_actuel: Optional[float] = None
    statut: str = "actif"
    mere_id: Optional[int] = None
    pere_id: Optional[int] = None
    notes: Optional[str] = None

class AnimalUpdate(BaseModel):
    nom: Optional[str] = None
    race_id: Optional[int] = None
    poids_actuel: Optional[float] = None
    statut: Optional[str] = None
    notes: Optional[str] = None

class PeseeCreate(BaseModel):
    animal_id: int
    poids_kg: float
    date_pesee: str
    agent: Optional[str] = "BoviBot"

class SanteCreate(BaseModel):
    animal_id: int
    type: str
    description: str
    date_acte: str
    veterinaire: Optional[str] = None
    medicament: Optional[str] = None
    cout: float = 0
    prochain_rdv: Optional[str] = None

class VenteCreate(BaseModel):
    animal_id: int
    acheteur: str
    telephone_acheteur: Optional[str] = None
    date_vente: str
    poids_vente_kg: Optional[float] = None
    prix_fcfa: float

class ReproCreate(BaseModel):
    mere_id: int
    pere_id: int
    date_saillie: str
    date_velage_prevue: Optional[str] = None
    notes: Optional[str] = None

# ── Routes CHAT ─────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(msg: ChatMessage):
    try:
        if msg.confirm_action and msg.pending_action:
            result = call_procedure(msg.pending_action["action"], msg.pending_action["params"])
            return {"type": "action_done", "answer": "✅ Action effectuée avec succès !", "data": []}

        llm = await ask_llm(msg.question, msg.history)
        t = llm.get("type", "info")

        if t == "query":
            sql = llm.get("sql")
            if not sql:
                return {"type": "info", "answer": llm.get("explication", ""), "data": []}
            try:
                data = execute_query(sql)
                return {"type": "query", "answer": llm.get("explication", ""), "data": data, "sql": sql, "count": len(data)}
            except Exception as e:
                return {"type": "error", "answer": f"Erreur SQL : {str(e)}", "data": []}

        elif t == "action":
            procedure_name = llm.get("procedure") or llm.get("action")
            return {
                "type": "action_pending",
                "answer": llm.get("explication", ""),
                "confirmation": llm.get("confirmation", "Confirmer cette action ?"),
                "pending_action": {"action": procedure_name, "params": llm.get("params", {})},
                "data": []
            }
        else:
            return {"type": "info", "answer": llm.get("explication", ""), "data": []}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Routes DASHBOARD ────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard():
    stats = {}
    queries = {
        "total_actifs":      "SELECT COUNT(*) as n FROM animaux WHERE statut='actif'",
        "femelles":          "SELECT COUNT(*) as n FROM animaux WHERE statut='actif' AND sexe='F'",
        "males":             "SELECT COUNT(*) as n FROM animaux WHERE statut='actif' AND sexe='M'",
        "en_gestation":      "SELECT COUNT(*) as n FROM reproduction WHERE statut='en_gestation'",
        "alertes_actives":   "SELECT COUNT(*) as n FROM alertes WHERE traitee=FALSE",
        "alertes_critiques": "SELECT COUNT(*) as n FROM alertes WHERE traitee=FALSE AND niveau='critical'",
        "ventes_mois":       "SELECT COUNT(*) as n FROM ventes WHERE MONTH(date_vente)=MONTH(NOW()) AND YEAR(date_vente)=YEAR(NOW())",
        "ca_mois":           "SELECT COALESCE(SUM(prix_fcfa),0) as n FROM ventes WHERE MONTH(date_vente)=MONTH(NOW()) AND YEAR(date_vente)=YEAR(NOW())",
        "pesees_mois":       "SELECT COUNT(*) as n FROM pesees WHERE MONTH(date_pesee)=MONTH(NOW()) AND YEAR(date_pesee)=YEAR(NOW())",
        "poids_moyen":       "SELECT COALESCE(ROUND(AVG(poids_actuel),0),0) as n FROM animaux WHERE statut='actif' AND poids_actuel IS NOT NULL",
    }
    for k, sql in queries.items():
        result = execute_query(sql)
        stats[k] = result[0]["n"] if result else 0
    return stats

# ── Routes ANIMAUX (CRUD complet) ───────────────────────────────
@app.get("/api/animaux")
def get_animaux(
    search: Optional[str] = Query(None),
    statut: Optional[str] = Query(None),
    sexe: Optional[str] = Query(None),
    race_id: Optional[int] = Query(None),
):
    STATUTS_VALIDES = {'actif', 'vendu', 'mort', 'quarantaine'}
    SEXES_VALIDES = {'M', 'F'}

    conditions = []
    if statut and statut in STATUTS_VALIDES:
        conditions.append(f"a.statut = '{statut}'")
    else:
        conditions.append("a.statut = 'actif'")
    if sexe and sexe in SEXES_VALIDES:
        conditions.append(f"a.sexe = '{sexe}'")
    if race_id:
        conditions.append(f"a.race_id = {race_id}")
    if search:
        s = search.replace("'", "''").replace("\\", "\\\\")[:100]
        conditions.append(f"(a.numero_tag LIKE '%{s}%' OR a.nom LIKE '%{s}%')")

    where = "WHERE " + " AND ".join(conditions)
    return execute_query(f"""
        SELECT a.*, r.nom as race, fn_age_en_mois(a.id) as age_mois,
               fn_gmq(a.id) as gmq_kg_jour
        FROM animaux a
        LEFT JOIN races r ON a.race_id = r.id
        {where}
        ORDER BY a.numero_tag
        LIMIT 200
    """)

@app.get("/api/animaux/{animal_id}")
def get_animal(animal_id: int):
    rows = execute_query(f"""
        SELECT a.*, r.nom as race, fn_age_en_mois(a.id) as age_mois,
               fn_gmq(a.id) as gmq_kg_jour,
               m.numero_tag as mere_tag, m.nom as mere_nom,
               p.numero_tag as pere_tag, p.nom as pere_nom
        FROM animaux a
        LEFT JOIN races r ON a.race_id = r.id
        LEFT JOIN animaux m ON a.mere_id = m.id
        LEFT JOIN animaux p ON a.pere_id = p.id
        WHERE a.id = {animal_id}
    """)
    if not rows:
        raise HTTPException(404, "Animal non trouvé")
    return rows[0]

@app.post("/api/animaux", status_code=201)
def create_animal(data: AnimalCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO animaux (numero_tag, nom, race_id, sexe, date_naissance,
                                  poids_actuel, statut, mere_id, pere_id, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (data.numero_tag, data.nom, data.race_id, data.sexe, data.date_naissance,
              data.poids_actuel, data.statut, data.mere_id, data.pere_id, data.notes))
        conn.commit()
        new_id = cursor.lastrowid
        return {"success": True, "id": new_id}
    except mysql.connector.IntegrityError as e:
        raise HTTPException(400, f"Erreur : {str(e)}")
    finally:
        cursor.close(); conn.close()

@app.put("/api/animaux/{animal_id}")
def update_animal(animal_id: int, data: AnimalUpdate):
    fields = {}
    if data.nom is not None: fields["nom"] = data.nom
    if data.race_id is not None: fields["race_id"] = data.race_id
    if data.poids_actuel is not None: fields["poids_actuel"] = data.poids_actuel
    if data.statut is not None: fields["statut"] = data.statut
    if data.notes is not None: fields["notes"] = data.notes
    if not fields:
        raise HTTPException(400, "Aucun champ à mettre à jour")
    set_clause = ", ".join([f"{k}=%s" for k in fields])
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE animaux SET {set_clause} WHERE id=%s",
                       list(fields.values()) + [animal_id])
        conn.commit()
        return {"success": True}
    finally:
        cursor.close(); conn.close()

@app.delete("/api/animaux/{animal_id}")
def delete_animal(animal_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE animaux SET statut='mort' WHERE id=%s", (animal_id,))
        conn.commit()
        return {"success": True, "message": "Animal marqué comme décédé"}
    finally:
        cursor.close(); conn.close()

# ── Routes PESÉES ───────────────────────────────────────────────
@app.get("/api/animaux/{animal_id}/pesees")
def get_pesees(animal_id: int):
    return execute_query(f"""
        SELECT * FROM pesees WHERE animal_id={animal_id} ORDER BY date_pesee DESC LIMIT 50
    """)

@app.get("/api/animaux/{animal_id}/historique")
def get_historique_statut(animal_id: int):
    return execute_query(f"""
        SELECT h.*, a.numero_tag, a.nom as animal_nom
        FROM historique_statut h
        JOIN animaux a ON h.animal_id = a.id
        WHERE h.animal_id = {animal_id}
        ORDER BY h.date_changement DESC
        LIMIT 50
    """)

@app.post("/api/pesees")
def add_pesee(data: PeseeCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.callproc("sp_enregistrer_pesee",
                        [data.animal_id, data.poids_kg, data.date_pesee, data.agent])
        conn.commit()
        return {"success": True}
    except mysql.connector.Error as e:
        raise HTTPException(400, str(e))
    finally:
        cursor.close(); conn.close()

# ── Routes SANTÉ ─────────────────────────────────────────────────
@app.get("/api/sante")
def get_sante(animal_id: Optional[int] = Query(None)):
    where = f"WHERE s.animal_id={animal_id}" if animal_id else ""
    return execute_query(f"""
        SELECT s.*, a.numero_tag, a.nom as animal_nom
        FROM sante s
        LEFT JOIN animaux a ON s.animal_id = a.id
        {where}
        ORDER BY s.date_acte DESC LIMIT 100
    """)

@app.post("/api/sante")
def add_sante(data: SanteCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO sante (animal_id, type, description, date_acte,
                               veterinaire, medicament, cout, prochain_rdv)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (data.animal_id, data.type, data.description, data.date_acte,
              data.veterinaire, data.medicament, data.cout,
              data.prochain_rdv if data.prochain_rdv else None))
        conn.commit()
        return {"success": True, "id": cursor.lastrowid}
    finally:
        cursor.close(); conn.close()

# ── Routes ALERTES ───────────────────────────────────────────────
@app.get("/api/alertes")
def get_alertes(niveau: Optional[str] = Query(None)):
    NIVEAUX_VALIDES = {'info', 'warning', 'critical'}
    where = "WHERE al.traitee=FALSE"
    if niveau and niveau in NIVEAUX_VALIDES:
        where += f" AND al.niveau='{niveau}'"
    return execute_query(f"""
        SELECT al.*, a.numero_tag, a.nom as animal_nom
        FROM alertes al
        LEFT JOIN animaux a ON al.animal_id = a.id
        {where}
        ORDER BY FIELD(al.niveau,'critical','warning','info'), al.date_creation DESC
        LIMIT 50
    """)

@app.post("/api/alertes/{alert_id}/traiter")
def traiter_alerte(alert_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE alertes SET traitee=TRUE WHERE id=%s", (alert_id,))
    conn.commit()
    cursor.close(); conn.close()
    return {"success": True}

# ── Routes REPRODUCTION ──────────────────────────────────────────
@app.get("/api/reproduction/en-cours")
def get_gestations():
    return execute_query("""
        SELECT r.*, a.numero_tag as mere_tag, a.nom as mere_nom,
               p.numero_tag as pere_tag,
               DATEDIFF(r.date_velage_prevue, CURDATE()) as jours_restants
        FROM reproduction r
        JOIN animaux a ON r.mere_id = a.id
        JOIN animaux p ON r.pere_id = p.id
        WHERE r.statut = 'en_gestation'
        ORDER BY r.date_velage_prevue ASC
    """)

@app.post("/api/reproduction")
def add_reproduction(data: ReproCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        prevue = data.date_velage_prevue
        if not prevue:
            cursor.execute(
                "SELECT DATE_ADD(%s, INTERVAL 283 DAY) as d",
                (data.date_saillie,)
            )
            r = cursor.fetchone()
            prevue = r[0].isoformat() if r else None
        cursor.execute("""
            INSERT INTO reproduction (mere_id, pere_id, date_saillie, date_velage_prevue, notes, statut)
            VALUES (%s,%s,%s,%s,%s,'en_gestation')
        """, (data.mere_id, data.pere_id, data.date_saillie, prevue, data.notes))
        conn.commit()
        return {"success": True, "id": cursor.lastrowid, "date_velage_prevue": prevue}
    finally:
        cursor.close(); conn.close()

# ── Routes VENTES ─────────────────────────────────────────────────
@app.get("/api/ventes")
def get_ventes():
    return execute_query("""
        SELECT v.*, a.numero_tag, a.nom as animal_nom
        FROM ventes v
        LEFT JOIN animaux a ON v.animal_id = a.id
        ORDER BY v.date_vente DESC LIMIT 50
    """)

@app.post("/api/ventes")
def add_vente(data: VenteCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.callproc("sp_declarer_vente", [
            data.animal_id, data.acheteur,
            data.telephone_acheteur or "", data.prix_fcfa,
            data.poids_vente_kg or 0, data.date_vente
        ])
        conn.commit()
        return {"success": True}
    except mysql.connector.Error as e:
        raise HTTPException(400, str(e))
    finally:
        cursor.close(); conn.close()

# ── Routes ALIMENTATION ───────────────────────────────────────────
class AlimentationCreate(BaseModel):
    animal_id: int
    type_aliment: str
    quantite_kg: float
    date_alimentation: str
    cout_unitaire_kg: float = 0.0

@app.get("/api/alimentation")
def get_alimentation(animal_id: Optional[int] = Query(None)):
    where = f"WHERE al.animal_id = {animal_id}" if animal_id else ""
    return execute_query(f"""
        SELECT al.*, a.numero_tag, a.nom as animal_nom,
               ROUND(al.quantite_kg * al.cout_unitaire_kg, 2) as cout_total
        FROM alimentation al
        LEFT JOIN animaux a ON al.animal_id = a.id
        {where}
        ORDER BY al.date_alimentation DESC
        LIMIT 100
    """)

@app.post("/api/alimentation", status_code=201)
def add_alimentation(data: AlimentationCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO alimentation (animal_id, type_aliment, quantite_kg,
                                      date_alimentation, cout_unitaire_kg)
            VALUES (%s, %s, %s, %s, %s)
        """, (data.animal_id, data.type_aliment, data.quantite_kg,
              data.date_alimentation, data.cout_unitaire_kg))
        conn.commit()
        return {"success": True, "id": cursor.lastrowid}
    finally:
        cursor.close(); conn.close()

@app.get("/api/alimentation/stats")
def get_alimentation_stats():
    return execute_query("""
        SELECT a.numero_tag, a.nom,
               ROUND(SUM(al.quantite_kg * al.cout_unitaire_kg), 0) as cout_total_fcfa,
               COUNT(*) as nb_repas,
               MAX(al.date_alimentation) as dernier_repas
        FROM alimentation al
        JOIN animaux a ON al.animal_id = a.id
        GROUP BY a.id, a.numero_tag, a.nom
        ORDER BY cout_total_fcfa DESC
    """)

# ── Routes RACES ──────────────────────────────────────────────────
@app.get("/api/races")
def get_races():
    return execute_query("SELECT * FROM races ORDER BY nom")

# ── Servir le frontend ────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/health")
def health():
    try:
        execute_query("SELECT 1")
        db_status = "ok"
    except:
        db_status = "error"
    return {
        "status": "ok",
        "app": "BoviBot",
        "version": "2.0.0",
        "database": db_status,
        "llm_configured": bool(LLM_API_KEY)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8002, reload=True)
