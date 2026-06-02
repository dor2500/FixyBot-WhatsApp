const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const axios = require('axios');

// Initialize the WhatsApp client
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process', // This saves a lot of memory!
            '--disable-gpu'
        ]
    }
});

// Generate and save QR code as image, and print to terminal (for Render logs)
client.on('qr', (qr) => {
    console.log('\n=========================================');
    console.log('סרוק את הברקוד הבא כדי לחבר את הבוט:');
    console.log('=========================================\n');
    
    // Print to terminal for Render/Linux
    qrcodeTerminal.generate(qr, {small: true});
    
    // Also save as image locally for Windows fallback
    QRCode.toFile('qr.png', qr, {
        color: {
            dark: '#000000',
            light: '#FFFFFF'
        }
    }, function (err) {
        if (!err) console.log('קובץ גיבוי qr.png נוצר בהצלחה.');
    });
});

// Confirmation when successfully connected
client.on('ready', () => {
    console.log('\n✅ הלקוח מחובר בהצלחה לווצאפ!');
    console.log('הבוט עכשיו מקשיב להודעות נכנסות...');
});

// Listen to incoming messages
client.on('message', async (message) => {
    // Only process standard text messages
    if (message.type !== 'chat') return;
    
    const chat = await message.getChat();
    
    let textToSend = message.body;
    
    // In groups, only reply if the bot is explicitly mentioned
    if (chat.isGroup) {
        const mentions = await message.getMentions();
        // Check if the bot's own ID is in the mentions list
        const isMentioned = mentions.some(contact => contact.id._serialized === client.info.wid._serialized);
        
        if (!isMentioned) {
            return; // Ignore group messages that don't tag the bot
        }
        
        // Remove ALL mentions from the text so the AI doesn't get confused by "@508..."
        textToSend = textToSend.replace(/@\d+\s*/g, '').trim();
    }

    console.log(`📩 הודעה חדשה מ-${message.from}: ${message.body}`);
    
    try {
        // Show "typing..." in WhatsApp
        chat.sendStateTyping();

        // Send the message text and sender ID to our Python backend
        const response = await axios.post('http://127.0.0.1:5000/api/chat', {
            phone: message.from,
            text: textToSend
        }, {
            timeout: 60000 // Give the AI up to 60 seconds to respond
        });

        const replyText = response.data.response;
        
        // Stop typing indicator and send the actual reply
        chat.clearState();
        if (replyText) {
            await client.sendMessage(message.from, replyText);
            console.log(`✅ תשובה נשלחה.`);
            
            // Auto-archive private chats so they don't clutter the user's inbox
            if (!chat.isGroup) {
                try {
                    await chat.archive();
                    console.log(`📦 שיחה הועברה לארכיון.`);
                } catch (err) {
                    console.log(`⚠️ לא ניתן היה להעביר לארכיון: ${err.message}`);
                }
            }
        }
    } catch (error) {
        console.error('❌ שגיאה בתקשורת עם השרת של פייתון:', error.message);
        chat.clearState();
        client.sendMessage(message.from, '⚠️ מצטער, נראה שיש לי תקלה זמנית. אנא נסה שוב מאוחר יותר.');
    }
});

// Start the client
console.log('מפעיל את שרת הגישור לווצאפ...');
client.initialize();
