/**
 * Serveur Pay.Genius → OTP (BS-XXXXXX) → WhatsApp
 * Stockage persistant PostgreSQL (table paiements).
 */

require("dotenv").config();

const express = require("express");
const cors = require("cors");
const path = require("path");
const { Pool } = require("pg");

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const WHATSAPP_NUMBER = "+2250140707502";
const PUBLIC_BASE_URL = String(process.env.PUBLIC_BASE_URL || `http://localhost:${PORT}`).replace(
  /\/$/,
  ""
);

const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error("DATABASE_URL manquante — configurez la variable d'environnement.");
  process.exit(1);
}

const pool = new Pool({
  connectionString: DATABASE_URL,
  ssl: DATABASE_URL.includes("localhost") || DATABASE_URL.includes("127.0.0.1")
    ? false
    : { rejectUnauthorized: false },
});

const SUCCESS_STATUS_VALUES = new Set([
  "success",
  "succeeded",
  "paid",
  "completed",
  "confirmed",
  "valide",
  "validé",
  "valid",
  "approved",
  "approve",
  "payment.success",
]);

const STATUS_FIELD_NAMES = ["status", "statut", "payment_status", "transaction_status"];
const EVENT_FIELD_NAMES = ["event", "type", "event_type", "action"];

// ——— Middleware ———
app.use(cors());
app.use(express.json({ limit: "1mb" }));
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, "..")));

/**
 * Parcourt un objet (et sous-objets) pour trouver la première valeur d'une clé (insensible à la casse).
 */
function findValueByKey(obj, keyName, depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 6) return undefined;
  const target = keyName.toLowerCase();

  for (const [k, v] of Object.entries(obj)) {
    if (k.toLowerCase() === target && v != null && v !== "") {
      return v;
    }
  }
  for (const v of Object.values(obj)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const found = findValueByKey(v, keyName, depth + 1);
      if (found !== undefined) return found;
    }
  }
  return undefined;
}

/**
 * Indique si le payload webhook signale un paiement confirmé (payment.success ou statut réussi).
 */
function isPaymentConfirmed(payload) {
  for (const field of EVENT_FIELD_NAMES) {
    const raw = findValueByKey(payload, field);
    if (raw == null) continue;
    const normalized = String(raw).toLowerCase().trim();
    if (normalized === "payment.success" || normalized === "payment_success") {
      return true;
    }
  }

  for (const field of STATUS_FIELD_NAMES) {
    const raw = findValueByKey(payload, field);
    if (raw == null) continue;
    const normalized = String(raw).toLowerCase().trim();
    if (SUCCESS_STATUS_VALUES.has(normalized)) {
      return true;
    }
  }
  return false;
}

/**
 * Extrait nom, email, téléphone et montant depuis le payload (plusieurs noms possibles).
 */
function extractCustomerData(payload) {
  const nom =
    findValueByKey(payload, "nom") ||
    findValueByKey(payload, "name") ||
    findValueByKey(payload, "customer_name") ||
    findValueByKey(payload, "client_name") ||
    null;

  const email =
    findValueByKey(payload, "email") ||
    findValueByKey(payload, "customer_email") ||
    findValueByKey(payload, "client_email") ||
    null;

  const telephone =
    findValueByKey(payload, "telephone") ||
    findValueByKey(payload, "phone") ||
    findValueByKey(payload, "mobile") ||
    findValueByKey(payload, "customer_phone") ||
    findValueByKey(payload, "numero") ||
    null;

  const montant =
    findValueByKey(payload, "montant") ||
    findValueByKey(payload, "amount") ||
    findValueByKey(payload, "price") ||
    findValueByKey(payload, "total") ||
    null;

  return {
    nom: nom != null ? String(nom).trim() : null,
    email: email != null ? String(email).trim() : null,
    telephone: telephone != null ? String(telephone).trim() : null,
    montant: montant != null ? String(montant).trim() : null,
  };
}

function extractPaymentStatus(payload) {
  for (const field of [...EVENT_FIELD_NAMES, ...STATUS_FIELD_NAMES]) {
    const raw = findValueByKey(payload, field);
    if (raw != null && String(raw).trim() !== "") {
      return String(raw).trim();
    }
  }
  return "success";
}

/**
 * Génère un code unique BS-XXXXXX (6 caractères alphanumériques).
 */
async function generateUniqueCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let attempts = 0;

  while (attempts < 50) {
    let suffix = "";
    for (let i = 0; i < 6; i++) {
      suffix += chars[Math.floor(Math.random() * chars.length)];
    }
    const code = `BS-${suffix}`;

    const existing = await pool.query("SELECT 1 FROM paiements WHERE code = $1 LIMIT 1", [code]);
    if (existing.rowCount === 0) {
      return code;
    }
    attempts++;
  }

  throw new Error("Impossible de générer un code unique après plusieurs tentatives.");
}

async function initDatabase() {
  const client = await pool.connect();
  try {
    console.log("Connexion PostgreSQL réussie");

    await client.query(`
      CREATE TABLE IF NOT EXISTS paiements (
        id SERIAL PRIMARY KEY,
        reference VARCHAR(255) UNIQUE NOT NULL,
        code VARCHAR(20) NOT NULL UNIQUE,
        nom_client VARCHAR(255),
        email_client VARCHAR(255),
        telephone_client VARCHAR(50),
        montant VARCHAR(50),
        statut VARCHAR(100),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    console.log("Création automatique de la table paiements (OK)");
  } finally {
    client.release();
  }
}

async function findPaiementByReference(reference) {
  const result = await pool.query(
    "SELECT * FROM paiements WHERE reference = $1 LIMIT 1",
    [String(reference)]
  );
  return result.rows[0] || null;
}

async function findPaiementByCode(code) {
  const result = await pool.query(
    "SELECT * FROM paiements WHERE code = $1 LIMIT 1",
    [code]
  );
  return result.rows[0] || null;
}

async function insertPaiement({ reference, code, nom, email, telephone, montant, statut }) {
  const result = await pool.query(
    `INSERT INTO paiements (reference, code, nom_client, email_client, telephone_client, montant, statut)
     VALUES ($1, $2, $3, $4, $5, $6, $7)
     RETURNING *`,
    [reference, code, nom, email, telephone, montant, statut]
  );
  return result.rows[0];
}

function mapPaiementToVerifyResponse(row) {
  return {
    code: row.code,
    nom: row.nom_client,
    telephone: row.telephone_client,
    montant: row.montant,
    date: row.created_at,
    used: false,
  };
}

function mapPaiementToListItem(row) {
  return {
    code: row.code,
    nom: row.nom_client,
    email: row.email_client,
    telephone: row.telephone_client,
    montant: row.montant,
    statut: row.statut,
    reference: row.reference,
    date: row.created_at,
    used: false,
  };
}

/**
 * Construit le message WhatsApp avec le code d'accès.
 */
function buildWhatsAppMessage(code) {
  return `Bonjour Blake Service, j'ai payé. Voici mon code d'accès : ${code}`;
}

/**
 * Lien wa.me avec message encodé.
 */
function buildWhatsAppUrl(code) {
  if (!WHATSAPP_NUMBER) {
    throw new Error("WHATSAPP_NUMBER manquant dans .env");
  }
  const text = encodeURIComponent(buildWhatsAppMessage(code));
  return `https://wa.me/${WHATSAPP_NUMBER.replace(/\D/g, "")}?text=${text}`;
}

function normalizeCodeParam(raw) {
  if (!raw || typeof raw !== "string") return null;
  const code = raw.trim().toUpperCase();
  if (!/^BS-[A-Z0-9]{6}$/.test(code)) return null;
  return code;
}

function buildPaymentResponse(code) {
  return {
    success: true,
    code,
    verifyUrl: `${PUBLIC_BASE_URL}/verify-code?code=${encodeURIComponent(code)}`,
    whatsappUrl: buildWhatsAppUrl(code),
  };
}

// ——— Santé ———
app.get("/", (_req, res) => {
  res.sendFile(path.join(__dirname, "..", "index.html"));
});

// ——— Webhook Pay.Genius (URL courte) ———
app.post("/webhook", (req, res) => {
  console.log("🔥 Webhook reçu !");
  console.log(req.body);

  res.status(200).send("OK");
});

// ——— 1. Webhook Pay.Genius (OTP + codes) ———
app.post("/webhook-paygenius", async (req, res) => {
  try {
    const payload = req.body ?? {};

    console.log("[webhook-paygenius] Payload reçu :");
    console.log(JSON.stringify(payload, null, 2));

    if (!isPaymentConfirmed(payload)) {
      console.log("[webhook-paygenius] Paiement non confirmé — aucun code généré.");
      return res.status(200).json({
        success: false,
        message: "Paiement non confirmé",
      });
    }

    const reference = findValueByKey(payload, "reference");

    if (reference == null || String(reference).trim() === "") {
      console.log("[webhook-paygenius] Référence manquante — impossible d'enregistrer le paiement.");
      return res.status(400).json({
        success: false,
        message: "Référence de paiement manquante",
      });
    }

    const referenceKey = String(reference).trim();
    const existing = await findPaiementByReference(referenceKey);

    if (existing) {
      console.log(`Paiement déjà existant (reference: ${referenceKey}, code: ${existing.code})`);
      return res.status(200).json({
        ...buildPaymentResponse(existing.code),
        message: "déjà traité",
      });
    }

    const { nom, email, telephone, montant } = extractCustomerData(payload);
    const statut = extractPaymentStatus(payload);
    const code = await generateUniqueCode();

    await insertPaiement({
      reference: referenceKey,
      code,
      nom,
      email,
      telephone,
      montant,
      statut,
    });

    console.log(`Paiement enregistré (reference: ${referenceKey}, code: ${code}, client: ${nom || "inconnu"})`);

    return res.status(200).json(buildPaymentResponse(code));
  } catch (err) {
    console.error("[webhook-paygenius] Erreur :", err);
    return res.status(500).json({
      success: false,
      message: "Erreur serveur",
      error: err.message,
    });
  }
});

// ——— 2. Vérifier un code ———
app.get("/verify-code", async (req, res) => {
  try {
    const code = normalizeCodeParam(req.query.code);

    if (!code) {
      return res.status(400).json({
        success: false,
        message: "CODE_INVALIDE",
        error: "Paramètre code manquant ou format invalide (attendu : BS-XXXXXX)",
      });
    }

    const record = await findPaiementByCode(code);

    if (!record) {
      return res.status(404).json({
        success: false,
        message: "CODE_INVALIDE",
      });
    }

    return res.status(200).json({
      success: true,
      message: "CODE_VALIDE",
      data: mapPaiementToVerifyResponse(record),
    });
  } catch (err) {
    console.error("[verify-code] Erreur :", err);
    return res.status(500).json({
      success: false,
      message: "Erreur serveur",
      error: err.message,
    });
  }
});

// ——— 3. Lien WhatsApp pour un code ———
app.get("/generate-link", async (req, res) => {
  try {
    const code = normalizeCodeParam(req.query.code);

    if (!code) {
      return res.status(400).json({
        success: false,
        message: "CODE_INVALIDE",
        error: "Paramètre code manquant ou format invalide (attendu : BS-XXXXXX)",
      });
    }

    const record = await findPaiementByCode(code);

    if (!record) {
      return res.status(404).json({
        success: false,
        message: "CODE_INVALIDE",
      });
    }

    const whatsappUrl = buildWhatsAppUrl(code);

    return res.status(200).json({
      success: true,
      code,
      whatsappUrl,
    });
  } catch (err) {
    console.error("[generate-link] Erreur :", err);
    return res.status(500).json({
      success: false,
      message: "Erreur serveur",
      error: err.message,
    });
  }
});

// ——— 4. Liste des codes (test) ———
app.get("/codes", async (_req, res) => {
  try {
    const result = await pool.query(
      "SELECT * FROM paiements ORDER BY created_at DESC"
    );
    const list = result.rows.map(mapPaiementToListItem);

    return res.status(200).json({
      success: true,
      count: list.length,
      codes: list,
    });
  } catch (err) {
    console.error("[codes] Erreur :", err);
    return res.status(500).json({
      success: false,
      error: err.message,
    });
  }
});

app.post("/create-payment", async (req, res) => {
  try {
    const apiKey = process.env.GENIUSPAY_API_KEY;
    const apiSecret = process.env.GENIUSPAY_API_SECRET;
    const baseUrl = process.env.GENIUSPAY_BASE_URL || "https://geniuspay.ci/api/v1/merchant";

    const response = await fetch(`${baseUrl}/payments`, {
      method: "POST",
      headers: {
        "X-API-Key": apiKey,
        "X-API-Secret": apiSecret,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        amount: 3700,
        description: "Formation IA - Accès formation 3700F",
        success_url: `${PUBLIC_BASE_URL}/confirmation.html`,
        error_url: `${PUBLIC_BASE_URL}/`,
        customer: {
          name: req.body.name || "Client",
          email: req.body.email || "",
          phone: req.body.phone || "",
        },
        metadata: {
          product: "formation-ia-3700",
        },
      }),
    });

    const rawText = await response.text();
    console.log("Réponse brute GeniusPay :", rawText.slice(0, 1000));

    let result;
    try {
      result = JSON.parse(rawText);
    } catch (e) {
      return res.status(500).json({
        success: false,
        message: "GeniusPay n'a pas renvoyé du JSON",
        status: response.status,
        preview: rawText.slice(0, 300),
      });
    }
    console.log("Paiement créé :", result);

    if (!result.success) {
      return res.status(400).json(result);
    }

    return res.redirect(result.data.checkout_url || result.data.payment_url);
  } catch (err) {
    console.error("Erreur create-payment :", err);
    return res.status(500).json({ success: false, error: err.message });
  }
});

// ——— Démarrage ———
async function start() {
  try {
    await initDatabase();

    app.listen(PORT, () => {
      console.log("GENIUSPAY_BASE_URL =", process.env.GENIUSPAY_BASE_URL || "(absent)");
      console.log("GENIUSPAY_API_KEY =", (process.env.GENIUSPAY_API_KEY || "").slice(0, 10) + "...");
      console.log(`Serveur OTP Pay.Genius → WhatsApp : ${PUBLIC_BASE_URL}`);
      console.log(`Webhook : POST ${PUBLIC_BASE_URL}/webhook`);
      console.log(`Webhook OTP : POST ${PUBLIC_BASE_URL}/webhook-paygenius`);
      if (!WHATSAPP_NUMBER) {
        console.warn("⚠️  WHATSAPP_NUMBER non défini — configurez le fichier .env");
      }
    });
  } catch (err) {
    console.error("Échec de l'initialisation PostgreSQL :", err);
    process.exit(1);
  }
}

start();



