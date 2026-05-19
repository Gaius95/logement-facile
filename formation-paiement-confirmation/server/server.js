const express = require("express");
const cors = require("cors");
require("dotenv").config();

const app = express();

app.use(cors());
app.use(express.json());

app.get("/", (req, res) => {
  res.send("Serveur PayGenius WhatsApp OK");
});

app.post("/webhook", (req, res) => {
  console.log("Webhook reçu :", req.body);

  // ici tu pourras traiter PayGenius plus tard

  res.status(200).json({ message: "Webhook reçu" });
});

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log("Serveur lancé sur le port " + PORT);
});