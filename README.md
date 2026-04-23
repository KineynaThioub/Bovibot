# BoviBot — Gestion d'Élevage Bovin avec IA + PL/SQL
**Projet L3 — ESP/UCAD | Pr. Ahmath Bamba MBACKE**

---

## Structure du projet

```
BoviBot/
├── frontend/
│   └── index.html          → Interface web complète (dashboard + chat IA)
├── backend/
│   └── app.py              → API FastAPI (CRUD + LLM + PL/SQL)
├── database/
│   └── schema.sql          → Base MySQL avec PL/SQL (tables, procédures, triggers, events)
├── .env.example            → Template de configuration
├── requirements.txt        → Dépendances Python
├── Procfile                → Config déploiement Railway/Render
├── railway.json            → Config Railway
└── README.md
```

---

## Installation locale

### 1. Cloner et configurer
```bash
git clone https://github.com/votre-repo/bovibot.git
cd bovibot
cp .env.example .env
# Éditez .env avec vos valeurs
```

### 2. Base de données MySQL
```bash
mysql -u root -p < database/schema.sql
```

### 3. Backend Python
```bash
pip install -r requirements.txt
cd backend
uvicorn app:app --host 0.0.0.0 --port 8002 --reload
```

### 4. Ouvrir le frontend
Ouvrir `frontend/index.html` dans un navigateur, **ou** laisser FastAPI le servir sur http://localhost:8002

---

## Déploiement (Railway — recommandé)

1. << On a créez un compte sur [railway.app](https://railway.app)
2. Ajoutez un service **MySQL** depuis le dashboard Railway
3. Importez votre dépôt GitHub
4. Dans les variables d'environnement, on a ajoutez :
   - `DB_HOST` → host fourni par Railway MySQL
   - `DB_USER`, `DB_PASSWORD`, `DB_NAME`
   - `OPENAI_API_KEY` → votre clé OpenAI
   - `LLM_MODEL` → `gpt-4o-mini`
5. Dans le terminal Railway, exécutez :
   ```bash
   mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD $DB_NAME < database/schema.sql
   ```
6. App  accessible sur `https://bovibot.railway.app`

### Render
1. Créez un service Web sur [render.com](https://render.com)
2. Build command : `pip install -r requirements.txt`
3. Start command : `cd backend && uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Ajoutez les variables d'environnement

---

## Configuration LLM


### Ollama local
```bash
# Installer Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3
ollama serve
```
```env
OPENAI_API_KEY=ollama
LLM_MODEL=llama3
LLM_BASE_URL=http://localhost:11434/v1
```

---

## API Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/health` | Statut de l'application |
| GET | `/api/dashboard` | Statistiques du tableau de bord |
| GET | `/api/animaux` | Liste des animaux (+ filtres : search, sexe, statut) |
| POST | `/api/animaux` | Créer un animal |
| PUT | `/api/animaux/{id}` | Modifier un animal |
| DELETE | `/api/animaux/{id}` | Supprimer (statut mort) |
| POST | `/api/pesees` | Enregistrer une pesée (sp_enregistrer_pesee) |
| GET | `/api/sante` | Actes vétérinaires |
| POST | `/api/sante` | Ajouter un acte vétérinaire |
| GET | `/api/alertes` | Alertes non traitées |
| POST | `/api/alertes/{id}/traiter` | Marquer une alerte comme traitée |
| GET | `/api/reproduction/en-cours` | Gestations en cours |
| POST | `/api/reproduction` | Déclarer une saillie |
| GET | `/api/ventes` | Historique des ventes |
| POST | `/api/ventes` | Déclarer une vente (sp_declarer_vente) |
| POST | `/api/chat` | Interface IA (Text-to-SQL + actions) |

---

##  Exemples de dialogues IA

**Consultation :**
> "Quels animaux ont un GMQ inférieur à 0.3 ?"
> "Liste les femelles en gestation"
> "Quel est le coût total d'alimentation ce mois ?"

**Action avec confirmation :**
> "Enregistre 320 kg pour TAG-001 aujourd'hui"
> → BoviBot affiche : "Confirmer : TAG-001 = 320 kg le 2026-04-09 ?"
> → Après confirmation → CALL sp_enregistrer_pesee(1, 320.0, '2026-04-09', 'BoviBot')

---

##  IA utilisees pour assistance

> ChatGPT
> Claude
> Gemini



# bovibot
