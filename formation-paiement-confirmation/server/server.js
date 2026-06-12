/**
 * Serveur Pay.Genius → OTP (BS-XXXXXX) → WhatsApp
 * Stockage temporaire en mémoire (Map), sans base de données.
 */

require("dotenv").config();

const express = require("express");
const cors = require("cors");

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const WHATSAPP_NUMBER = "+2250140707502";
const PUBLIC_BASE_URL = String(process.env.PUBLIC_BASE_URL || `http://localhost:${PORT}`).replace(
  /\/$/,
  ""
);

/** @type {Map<string, { code: string, nom: string|null, telephone: string|null, montant: string|null, date: string, used: boolean }>} */
const codesStore = new Map();

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
]);

const STATUS_FIELD_NAMES = ["status", "statut", "payment_status", "transaction_status"];

// ——— Middleware ———
app.use(cors());
app.use(express.json({ limit: "1mb" }));
app.use(express.urlencoded({ extended: true }));

/**
 * Parcourt un objet (et sous-objets) pour trouver la première valeur d’une clé (insensible à la casse).
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
 * Indique si le payload webhook signale un paiement confirmé.
 */
function isPaymentConfirmed(payload) {
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
 * Extrait nom, téléphone et montant depuis le payload (plusieurs noms possibles).
 */
function extractCustomerData(payload) {
  const nom =
    findValueByKey(payload, "nom") ||
    findValueByKey(payload, "name") ||
    findValueByKey(payload, "customer_name") ||
    findValueByKey(payload, "client_name") ||
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
    telephone: telephone != null ? String(telephone).trim() : null,
    montant: montant != null ? String(montant).trim() : null,
  };
}

/**
 * Génère un code unique BS-XXXXXX (6 caractères alphanumériques).
 */
function generateUniqueCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code;
  let attempts = 0;

  do {
    let suffix = "";
    for (let i = 0; i < 6; i++) {
      suffix += chars[Math.floor(Math.random() * chars.length)];
    }
    code = `BS-${suffix}`;
    attempts++;
    if (attempts > 50) {
      throw new Error("Impossible de générer un code unique après plusieurs tentatives.");
    }
  } while (codesStore.has(code));

  return code;
}

/**
 * Construit le message WhatsApp avec le code d’accès.
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

// ——— Santé ———
app.get("/", (_req, res) => {
  res.json({
    ok: true,
    service: "paygenius-whatsapp-otp",
    endpoints: [
      "POST /create-payment",
      "POST /webhook",
      "POST /webhook-paygenius",
      "GET /verify-code?code=BS-XXXXXX",
      "GET /generate-link?code=BS-XXXXXX",
      "GET /codes",
    ],
  });
});

// ——— Webhook Pay.Genius (URL courte) ———
app.post("/webhook", (req, res) => {
  console.log("🔥 Webhook reçu !");
  console.log(req.body);

  res.status(200).send("OK");
});

// ——— 1. Webhook Pay.Genius (OTP + codes) ———
app.post("/webhook-paygenius", (req, res) => {
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

    const { nom, telephone, montant } = extractCustomerData(payload);
    const code = generateUniqueCode();
    const date = new Date().toISOString();

    const record = {
      code,
      nom,
      telephone,
      montant,
      date,
      used: false,
    };

    codesStore.set(code, record);

    const verifyUrl = `${PUBLIC_BASE_URL}/verify-code?code=${encodeURIComponent(code)}`;
    const whatsappUrl = buildWhatsAppUrl(code);

    console.log(`[webhook-paygenius] Code créé : ${code} pour ${nom || "client inconnu"}`);

    return res.status(200).json({
      success: true,
      code,
      verifyUrl,
      whatsappUrl,
    });
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
app.get("/verify-code", (req, res) => {
  try {
    const code = normalizeCodeParam(req.query.code);

    if (!code) {
      return res.status(400).json({
        success: false,
        message: "CODE_INVALIDE",
        error: "Paramètre code manquant ou format invalide (attendu : BS-XXXXXX)",
      });
    }

    const record = codesStore.get(code);

    if (!record) {
      return res.status(404).json({
        success: false,
        message: "CODE_INVALIDE",
      });
    }

    return res.status(200).json({
      success: true,
      message: "CODE_VALIDE",
      data: {
        code: record.code,
        nom: record.nom,
        telephone: record.telephone,
        montant: record.montant,
        date: record.date,
        used: record.used,
      },
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
app.get("/generate-link", (req, res) => {
  try {
    const code = normalizeCodeParam(req.query.code);

    if (!code) {
      return res.status(400).json({
        success: false,
        message: "CODE_INVALIDE",
        error: "Paramètre code manquant ou format invalide (attendu : BS-XXXXXX)",
      });
    }

    const record = codesStore.get(code);

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

// ——— 4. Liste des codes (test local uniquement) ———
app.get("/codes", (_req, res) => {
  try {
    const list = Array.from(codesStore.values());
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
        preview: rawText.slice(0, 300)
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
app.listen(PORT, () => {
  console.log(`Serveur OTP Pay.Genius → WhatsApp : ${PUBLIC_BASE_URL}`);
  console.log(`Webhook : POST ${PUBLIC_BASE_URL}/webhook`);
  console.log(`Webhook OTP : POST ${PUBLIC_BASE_URL}/webhook-paygenius`);
  if (!WHATSAPP_NUMBER) {
    console.warn("⚠️  WHATSAPP_NUMBER non défini — configurez le fichier .env");
  }
});
