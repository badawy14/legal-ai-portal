// Application State
let state = {
    provider: 'gemini',
    gemini_api_key: '',
    lmstudio_url: 'http://localhost:1234/v1',
    lmstudio_model: 'qwen2.5-7b',
    local_library_path: '',
    documents: [],
    currentChatSources: {}, // Maps message_id -> sources array
    // Encyclopedia Data
    legislationLoaded: false,
    rulingsLoaded: false,
    templatesLoaded: false,
    templates: [],
    activeTemplateId: null,
    autoSpeak: false,
    currentAudioElement: null,
    tts_voice: localStorage.getItem('tts_voice') || 'auto',
    tts_rate: localStorage.getItem('tts_rate') || '+10%'
};

// DOM Elements
const syncLibraryBtn = document.getElementById('sync-library-btn');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const docsList = document.getElementById('docs-list');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const messagesContainer = document.getElementById('messages-container');
const clearChatBtn2 = document.getElementById('clear-chat-btn-2');

// Tab Labels & Headers
const activeProviderLabel = document.getElementById('active-provider-label');
const providerLabelTop = document.querySelector('.provider-label-top');
const sidebarPathLabel = document.getElementById('sidebar-path-label');
const syncLibraryPathLabel = document.getElementById('sync-library-path-label');

// Settings Elements
const settingsTrigger = document.getElementById('settings-trigger');
const settingsModal = document.getElementById('settings-modal');
const closeSettingsBtn = document.getElementById('close-settings-btn');
const cancelSettingsBtn = document.getElementById('cancel-settings-btn');
const saveSettingsBtn = document.getElementById('save-settings-btn');
const libraryPathInput = document.getElementById('library-path-input');
const providerSelect = document.getElementById('provider-select');
const geminiConfigSection = document.getElementById('gemini-config-section');
const lmstudioConfigSection = document.getElementById('lmstudio-config-section');
const geminiApiKeyInput = document.getElementById('gemini-api-key');
const toggleApiKeyVisBtn = document.getElementById('toggle-api-key-visibility');
const ocrEnabledCheckbox = document.getElementById('ocr-enabled-checkbox');
const lmstudioUrlInput = document.getElementById('lmstudio-url');
const lmstudioModelInput = document.getElementById('lmstudio-model');

// Sources Sidebar Elements
const sourcesSidebar = document.getElementById('sources-sidebar');
const closeSourcesBtn = document.getElementById('close-sources-btn');
const sourcesContent = document.getElementById('sources-content');

// Toast Element
const toast = document.getElementById('toast');

// --- Tab selectors ---
const menuItems = document.querySelectorAll('.menu-item');
const tabContents = document.querySelectorAll('.tab-content');

// --- Dashboard Elements ---
const statBooksCount = document.getElementById('stat-books-count');
const quickAskInput = document.getElementById('quick-ask-input');
const quickAskBtn = document.getElementById('quick-ask-btn');

// --- Legislation Search Elements ---
const legislationSearchInput = document.getElementById('legislation-search-input');
const legislationSearchBtn = document.getElementById('legislation-search-btn');
const legislationListContainer = document.getElementById('legislation-list-container');

// --- Rulings Search Elements ---
const rulingSearchInput = document.getElementById('ruling-search-input');
const rulingCategorySelect = document.getElementById('ruling-category-select');
const rulingSearchBtn = document.getElementById('ruling-search-btn');
const rulingsListContainer = document.getElementById('rulings-list-container');

// --- Templates Elements ---
const templatesListContainer = document.getElementById('templates-list-container');
const templateEditorTextarea = document.getElementById('template-editor-textarea');
const copyTemplateBtn = document.getElementById('copy-template-btn');
const activeTemplateTitle = document.getElementById('active-template-title');

// Authentication & Profile State
let currentUser = null;
let activeChatSessionId = null;
let chatSessions = [];

async function checkUserSession() {
    try {
        const response = await fetch('/api/auth/me');
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (data.logged_in) {
            currentUser = data.user;
            handleSuccessfulLogin();
        } else {
            showLoginOverlay();
        }
    } catch (e) {
        showLoginOverlay();
    }
}

function showLoginOverlay() {
    document.getElementById('login-overlay').style.display = 'flex';
    initGoogleSignIn();
}

function handleSuccessfulLogin() {
    document.getElementById('login-overlay').style.display = 'none';
    
    // Show user profile in sidebar
    const profileSec = document.getElementById('user-profile-section');
    profileSec.style.display = 'flex';
    document.getElementById('user-avatar').src = currentUser.picture || 'https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y';
    document.getElementById('user-name').textContent = currentUser.name;
    document.getElementById('user-email').textContent = currentUser.email;
    
    // If admin, show admin features and fetch stats
    const adminWidget = document.getElementById('admin-dashboard-widget');
    if (currentUser.is_admin) {
        adminWidget.style.display = 'block';
        loadAdminStats();
        
        // Ensure sync button is active for admins
        if (syncLibraryBtn) syncLibraryBtn.disabled = false;
        const syncTabMenuItem = document.querySelector('[data-tab="sync"]');
        if (syncTabMenuItem) syncTabMenuItem.style.display = 'flex';
    } else {
        adminWidget.style.display = 'none';
        
        // Hide sync tab or alert that only admin can sync
        const syncTabMenuItem = document.querySelector('[data-tab="sync"]');
        if (syncTabMenuItem) {
            syncTabMenuItem.style.display = 'none'; // Hide sync tab for non-admins
        }
    }
    
    // Load chat sessions
    loadChatSessions();
    
    // Load settings and documents
    loadSettingsFromServer();
    loadDocuments();
}

async function initGoogleSignIn() {
    if (typeof google !== 'undefined') {
        let clientId = "789123456789-mockclientid.apps.googleusercontent.com"; // Fallback mock ID
        try {
            const res = await fetch('/api/config');
            if (res.ok) {
                const config = await res.json();
                if (config.google_client_id && config.google_client_id.trim() !== "") {
                    clientId = config.google_client_id;
                }
            }
        } catch (err) {
            console.log("Error fetching client config, using fallback client ID:", err);
        }

        google.accounts.id.initialize({
            client_id: clientId,
            callback: handleCredentialResponse
        });
        google.accounts.id.renderButton(
            document.getElementById("google-signin-btn-container"),
            { theme: "outline", size: "large", width: 280 }
        );
    } else {
        console.log("Google Identity Services script not loaded. Fallback to dev login only.");
        document.getElementById("google-signin-btn-container").innerHTML = 
            `<p style="color:var(--text-muted); font-size:11px;">خدمات جوجل غير متاحة حالياً، يرجى استخدام الدخول للتجربة بالأسفل.</p>`;
    }
}

async function handleCredentialResponse(response) {
    try {
        const res = await fetch('/api/auth/google', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: response.credential })
        });
        if (!res.ok) throw new Error("فشلت المصادقة مع الخادم");
        const data = await res.json();
        currentUser = data.user;
        handleSuccessfulLogin();
        showToast("تم تسجيل الدخول بنجاح.");
    } catch (err) {
        showToast(err.message || "فشل تسجيل الدخول بواسطة Google", true);
    }
}

async function handleDevLogin() {
    const email = document.getElementById('dev-email-input').value.trim();
    if (!email || !email.includes('@')) {
        showToast("يرجى إدخال بريد إلكتروني صالح", true);
        return;
    }
    try {
        const res = await fetch('/api/auth/google', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: email })
        });
        if (!res.ok) throw new Error("فشل تسجيل الدخول للتجربة");
        const data = await res.json();
        currentUser = data.user;
        handleSuccessfulLogin();
        showToast("تم تسجيل الدخول للتجربة بنجاح.");
    } catch (err) {
        showToast(err.message, true);
    }
}

async function handleLogout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        currentUser = null;
        activeChatSessionId = null;
        chatSessions = [];
        document.getElementById('user-profile-section').style.display = 'none';
        document.getElementById('login-overlay').style.display = 'flex';
        showToast("تم تسجيل الخروج.");
        messagesContainer.innerHTML = '';
        renderChatSessions();
    } catch (e) {
        showToast("حدث خطأ أثناء تسجيل الخروج", true);
    }
}

async function handleEmailLogin() {
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    
    if (!email || !password) {
        showToast("يرجى إدخال البريد الإلكتروني وكلمة المرور.", true);
        return;
    }
    
    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "فشل تسجيل الدخول.");
        }
        
        currentUser = data.user;
        handleSuccessfulLogin();
        showToast("تم تسجيل الدخول بنجاح.");
    } catch (err) {
        showToast(err.message, true);
    }
}

async function handleEmailSignup() {
    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;
    
    if (!name || !email || !password) {
        showToast("يرجى ملء جميع الحقول المطلوبة.", true);
        return;
    }
    
    try {
        const res = await fetch('/api/auth/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password })
        });
        
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || "فشل إنشاء الحساب.");
        }
        
        currentUser = data.user;
        handleSuccessfulLogin();
        showToast("تم إنشاء الحساب وتسجيل الدخول بنجاح.");
    } catch (err) {
        showToast(err.message, true);
    }
}

async function loadAdminStats() {
    try {
        const res = await fetch('/api/admin/stats');
        if (!res.ok) return;
        const stats = await res.json();
        document.getElementById('admin-stat-users').textContent = stats.total_users;
        document.getElementById('admin-stat-docs').textContent = stats.total_docs;
        document.getElementById('admin-stat-chunks').textContent = stats.total_chunks;
        document.getElementById('admin-stat-size').textContent = `${stats.index_size_mb} MB`;
    } catch (e) {
        console.error("Failed to load admin stats: ", e);
    }
}

// Voice input (Speech-to-Text) using Web Speech API
function setupVoiceRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.log("Speech recognition not supported in this browser.");
        return;
    }
    
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'ar-EG';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    
    let activeInputEl = null;
    let activeBtnEl = null;
    
    recognition.onstart = () => {
        if (activeBtnEl) activeBtnEl.classList.add('mic-pulsing');
        showToast("جاري الاستماع... تحدث الآن");
    };
    
    recognition.onresult = (event) => {
        const resultText = event.results[0][0].transcript;
        if (activeInputEl) {
            if (activeInputEl.tagName === 'TEXTAREA' || activeInputEl.tagName === 'INPUT') {
                const startPos = activeInputEl.selectionStart;
                const endPos = activeInputEl.selectionEnd;
                const originalText = activeInputEl.value;
                activeInputEl.value = originalText.substring(0, startPos) + resultText + originalText.substring(endPos);
                activeInputEl.focus();
            }
        }
    };
    
    recognition.onerror = (event) => {
        console.error("Speech recognition error: ", event.error);
        showToast("حدث خطأ أثناء التعرف على الصوت: " + event.error, true);
        if (activeBtnEl) activeBtnEl.classList.remove('mic-pulsing');
    };
    
    recognition.onend = () => {
        if (activeBtnEl) activeBtnEl.classList.remove('mic-pulsing');
        activeInputEl = null;
        activeBtnEl = null;
    };
    
    function toggleListening(inputEl, btnEl) {
        if (activeBtnEl === btnEl) {
            recognition.stop();
        } else {
            if (activeBtnEl) {
                recognition.stop();
            }
            activeInputEl = inputEl;
            activeBtnEl = btnEl;
            recognition.start();
        }
    }
    
    const chatMicBtn = document.getElementById('chat-mic-btn');
    if (chatMicBtn) {
        chatMicBtn.addEventListener('click', () => {
            toggleListening(document.getElementById('chat-input'), chatMicBtn);
        });
    }
    
    const translateMicBtn = document.getElementById('translate-mic-btn');
    if (translateMicBtn) {
        translateMicBtn.addEventListener('click', () => {
            toggleListening(document.getElementById('translate-input-text'), translateMicBtn);
        });
    }
    
    const cbTermsMicBtn = document.getElementById('cb-terms-mic-btn');
    if (cbTermsMicBtn) {
        cbTermsMicBtn.addEventListener('click', () => {
            toggleListening(document.getElementById('cb-special-terms'), cbTermsMicBtn);
        });
    }

    const quickAskMicBtn = document.getElementById('quick-ask-mic-btn');
    if (quickAskMicBtn) {
        quickAskMicBtn.addEventListener('click', () => {
            toggleListening(document.getElementById('quick-ask-input'), quickAskMicBtn);
        });
    }
}

// Voice output (Text-to-Speech) using SpeechSynthesis API
let currentUtterance = null;

function setupVoiceSynthesis() {
    const translateSpeakBtn = document.getElementById('translate-speak-btn');
    if (translateSpeakBtn) {
        translateSpeakBtn.addEventListener('click', () => {
            const outText = document.getElementById('translate-output-text').textContent || '';
            const dir = document.getElementById('translation-direction').value;
            const lang = dir === 'ar-to-en' ? 'en-US' : 'ar-EG';
            speakText(outText, lang);
        });
    }
    
    const cbSpeakBtn = document.getElementById('cb-speak-btn');
    if (cbSpeakBtn) {
        cbSpeakBtn.addEventListener('click', () => {
            const contractText = document.getElementById('cb-output-area').innerText || '';
            speakText(contractText, 'ar-EG');
        });
    }

    // Auto-speak state & toggle setup
    state.autoSpeak = localStorage.getItem('auto_speak') === 'true';
    
    const toggleVoiceReplyBtn = document.getElementById('toggle-voice-reply-btn');
    const voiceReplyStatus = document.getElementById('voice-reply-status');
    
    function updateVoiceReplyUI() {
        if (toggleVoiceReplyBtn && voiceReplyStatus) {
            if (state.autoSpeak) {
                toggleVoiceReplyBtn.classList.add('btn-primary');
                toggleVoiceReplyBtn.classList.remove('btn-secondary');
                voiceReplyStatus.textContent = "مفعلة";
                const icon = toggleVoiceReplyBtn.querySelector('i');
                if (icon) {
                    icon.className = "fa-solid fa-volume-high";
                }
            } else {
                toggleVoiceReplyBtn.classList.remove('btn-primary');
                toggleVoiceReplyBtn.classList.add('btn-secondary');
                voiceReplyStatus.textContent = "معطلة";
                const icon = toggleVoiceReplyBtn.querySelector('i');
                if (icon) {
                    icon.className = "fa-solid fa-volume-xmark";
                }
            }
        }
    }
    
    if (toggleVoiceReplyBtn) {
        updateVoiceReplyUI();
        toggleVoiceReplyBtn.addEventListener('click', () => {
            state.autoSpeak = !state.autoSpeak;
            localStorage.setItem('auto_speak', state.autoSpeak);
            updateVoiceReplyUI();
            showToast(state.autoSpeak ? "تم تفعيل القراءة التلقائية للإجابات" : "تم تعطيل القراءة التلقائية للإجابات");
        });
    }
}

function speakText(text, lang = 'ar-EG', overrideVoice = null) {
    // Clean text from markdown formatting and citation tags for natural voice flow
    const cleanText = text
        .replace(/[\*\#\`\_\-\+\>]/g, '') // remove markdown syntax
        .replace(/\[المصدر \d+\]/g, '')   // remove [المصدر X] citations
        .replace(/\[.*?\]\(.*?\)/g, '')   // remove markdown links
        .trim();

    if (!cleanText) {
        showToast("لا يوجد نص مقروء للقراءة بصوت مسموع.", true);
        return;
    }
    
    // Toggle stop if clicked while playing (Cloud Audio)
    if (state.currentAudioElement && !state.currentAudioElement.paused) {
        state.currentAudioElement.pause();
        state.currentAudioElement = null;
        return;
    }
    
    // Toggle stop if clicked while playing (Web Speech API)
    if (window.speechSynthesis && window.speechSynthesis.speaking && currentUtterance && currentUtterance.text === cleanText) {
        window.speechSynthesis.cancel();
        currentUtterance = null;
        return;
    }
    
    // Always reset any running browser voice
    if (window.speechSynthesis) {
        try {
            window.speechSynthesis.resume();
            window.speechSynthesis.cancel();
        } catch (e) {
            console.error("Error resetting SpeechSynthesis:", e);
        }
    }
    
    // Always clear any playing cloud audio
    if (state.currentAudioElement) {
        state.currentAudioElement.pause();
        state.currentAudioElement = null;
    }

    const voiceToUse = overrideVoice || state.tts_voice;

    // Try our professional backend Neural TTS endpoint first (dynamic voice and speed)
    try {
        const url = `/api/tts?text=${encodeURIComponent(cleanText)}&voice=${encodeURIComponent(voiceToUse)}&rate=${encodeURIComponent(state.tts_rate)}`;
        const audio = new Audio(url);
        state.currentAudioElement = audio;
        
        audio.play()
            .then(() => {
                console.log("Playing speech via professional Neural edge-tts backend");
            })
            .catch((err) => {
                console.warn("Backend Neural TTS play failed, falling back to Web Speech API:", err);
                playWebSpeech(cleanText, lang);
            });
        return;
    } catch (e) {
        console.warn("Backend Neural TTS error, falling back to Web Speech API:", e);
    }

    // Fallback to local browser Web Speech API
    playWebSpeech(cleanText, lang);
}

function playWebSpeech(cleanText, lang) {
    if (!window.speechSynthesis) {
        showToast("ميزة القراءة الصوتية غير مدعومة في متصفحك.", true);
        return;
    }
    
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = lang;
    
    const voices = window.speechSynthesis.getVoices();
    let voice = voices.find(v => v.lang.toLowerCase().replace('_', '-').startsWith(lang.toLowerCase()));
    if (!voice && lang.startsWith('ar')) {
        voice = voices.find(v => v.lang.toLowerCase().startsWith('ar'));
    }
    
    if (voice) {
        utterance.voice = voice;
        console.log("Selected local voice:", voice.name);
    } else {
        console.warn("No Arabic voice found in local voices. Fallback to default browser voice.");
        showToast("تنبيه: لا يوجد محرك صوتي عربي مثبت بمتصفحك؛ قد يتم نطق الأرقام فقط بالإنجليزية.", false);
    }
    
    utterance.onerror = (event) => {
        console.error("Local SpeechSynthesis error: ", event);
        if (event.error !== 'interrupted' && event.error !== 'canceled') {
            showToast("خطأ أثناء تشغيل الصوت: " + event.error, true);
        }
    };
    
    currentUtterance = utterance;
    
    setTimeout(() => {
        window.speechSynthesis.speak(utterance);
    }, 50);
}

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    checkUserSession();
    setupRoutingHandlers();
    setupSyncHandlers();
    setupSettingsModalHandlers();
    setupChatHandlers();
    setupSourcesSidebarHandlers();
    setupDashboardQuickAsk();
    setupLegislationHandlers();
    setupRulingsHandlers();
    setupTemplatesHandlers();
    setupMobileNavigation();
    
    // Auth listeners
    document.getElementById('dev-login-btn').addEventListener('click', handleDevLogin);
    document.getElementById('logout-btn').addEventListener('click', handleLogout);
    
    // Email/Password login/signup UI toggle listeners
    const tabLoginBtn = document.getElementById('tab-login-btn');
    const tabSignupBtn = document.getElementById('tab-signup-btn');
    const loginFormBlock = document.getElementById('login-form-block');
    const signupFormBlock = document.getElementById('signup-form-block');
    
    if (tabLoginBtn && tabSignupBtn) {
        tabLoginBtn.addEventListener('click', () => {
            tabLoginBtn.classList.add('active');
            tabSignupBtn.classList.remove('active');
            loginFormBlock.style.display = 'block';
            signupFormBlock.style.display = 'none';
        });
        tabSignupBtn.addEventListener('click', () => {
            tabSignupBtn.classList.add('active');
            tabLoginBtn.classList.remove('active');
            signupFormBlock.style.display = 'block';
            loginFormBlock.style.display = 'none';
        });
    }
    
    // Toggle dev local bypass
    const toggleDevLink = document.getElementById('toggle-dev-login-link');
    const devLoginBlock = document.getElementById('dev-login-block');
    if (toggleDevLink && devLoginBlock) {
        toggleDevLink.addEventListener('click', (e) => {
            e.preventDefault();
            devLoginBlock.style.display = devLoginBlock.style.display === 'none' ? 'block' : 'none';
        });
    }
    
    // Email signup and login form handlers
    const emailLoginBtn = document.getElementById('email-login-btn');
    if (emailLoginBtn) emailLoginBtn.addEventListener('click', handleEmailLogin);
    
    const emailSignupBtn = document.getElementById('email-signup-btn');
    if (emailSignupBtn) emailSignupBtn.addEventListener('click', handleEmailSignup);
    
    // New chat button listener
    const newChatBtn = document.getElementById('new-chat-session-btn');
    if (newChatBtn) newChatBtn.addEventListener('click', startNewChatSession);
    
    // Voice & Audio listener setup
    setupVoiceRecognition();
    setupVoiceSynthesis();
    
    // Quick online/offline toggle listener
    const onlineOfflineBadge = document.getElementById('online-offline-badge');
    if (onlineOfflineBadge) {
        onlineOfflineBadge.addEventListener('click', toggleOnlineOfflineMode);
        onlineOfflineBadge.style.cursor = 'pointer';
        onlineOfflineBadge.title = 'اضغط للتبديل السريع بين الوضع السحابي والأوفلاين';
    }
});

// --- Settings & API Core ---

function showToast(message, isError = false) {
    toast.textContent = message;
    toast.className = 'toast';
    if (isError) toast.classList.add('error');
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 4500);
}

async function loadSettingsFromServer() {
    try {
        const response = await fetch('/api/settings');
        if (!response.ok) throw new Error();
        const settings = await response.json();
        
        state.provider = settings.provider;
        state.embedding_provider = settings.embedding_provider || 'local';
        state.gemini_api_key = settings.gemini_api_key;
        state.lmstudio_url = settings.lmstudio_url;
        state.lmstudio_model = settings.lmstudio_model;
        state.local_library_path = settings.local_library_path;
        state.ocr_enabled = settings.ocr_enabled || false;
        
        updateSettingsModalFields();
        updateHeaderStatus();
        
        // Update paths display
        sidebarPathLabel.textContent = state.local_library_path;
        sidebarPathLabel.title = state.local_library_path;
        syncLibraryPathLabel.textContent = state.local_library_path;
    } catch (error) {
        showToast("خطأ أثناء الاتصال بالخادم لقراءة الإعدادات.", true);
    }
}

function updateSettingsModalFields() {
    libraryPathInput.value = state.local_library_path;
    providerSelect.value = state.provider;
    const embedProviderSelect = document.getElementById('embed-provider-select');
    if (embedProviderSelect) embedProviderSelect.value = state.embedding_provider || 'local';
    geminiApiKeyInput.value = state.gemini_api_key;
    lmstudioUrlInput.value = state.lmstudio_url;
    lmstudioModelInput.value = state.lmstudio_model;
    ocrEnabledCheckbox.checked = state.ocr_enabled || false;
    
    const ttsVoiceSelect = document.getElementById('tts-voice-select');
    const ttsRateSelect = document.getElementById('tts-rate-select');
    if (ttsVoiceSelect) ttsVoiceSelect.value = state.tts_voice;
    if (ttsRateSelect) ttsRateSelect.value = state.tts_rate;
    
    toggleConfigSections(state.provider);
}

function toggleConfigSections(provider) {
    if (provider === 'gemini') {
        geminiConfigSection.style.display = 'block';
        lmstudioConfigSection.style.display = 'none';
    } else {
        geminiConfigSection.style.display = 'none';
        lmstudioConfigSection.style.display = 'block';
    }
}

function updateHeaderStatus() {
    const isGemini = state.provider === 'gemini';
    const activeLabel = isGemini ? 'Google Gemini API' : `محلي: LM Studio (${state.lmstudio_model})`;
    
    if (activeProviderLabel) {
        activeProviderLabel.textContent = `النموذج الفعال: ${activeLabel}`;
    }
    if (providerLabelTop) {
        providerLabelTop.textContent = `محرك الذكاء الاصطناعي: ${activeLabel}`;
    }
    
    const dot = document.querySelector('.status-dot');
    const badge = document.getElementById('online-offline-badge');
    
    if (isGemini && !state.gemini_api_key) {
        if (dot) dot.className = 'status-dot offline';
        if (activeProviderLabel) activeProviderLabel.innerHTML += ' <span style="color:#EF4444; font-size:11px;">(مفتاح API مفقود)</span>';
        if (providerLabelTop) providerLabelTop.innerHTML += ' <span style="color:#EF4444; font-size:11px;">(مفتاح API مفقود)</span>';
        if (badge) {
            badge.textContent = 'وضع سحابي (مفتاح مفقود)';
            badge.style.background = 'rgba(239, 68, 68, 0.15)';
            badge.style.color = '#ef4444';
            badge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
        }
    } else {
        if (dot) dot.className = 'status-dot online';
        if (badge) {
            if (isGemini) {
                badge.textContent = 'وضع سحابي (Google Gemini)';
                badge.style.background = 'rgba(14, 165, 233, 0.15)';
                badge.style.color = '#0ea5e9';
                badge.style.border = '1px solid rgba(14, 165, 233, 0.3)';
            } else {
                badge.textContent = 'وضع أوفلاين (محلي 100%)';
                badge.style.background = 'rgba(16, 185, 129, 0.15)';
                badge.style.color = '#10b981';
                badge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
            }
        }
    }
}

async function toggleOnlineOfflineMode() {
    const nextProvider = state.provider === 'gemini' ? 'lmstudio' : 'gemini';
    const nextProviderLabel = nextProvider === 'gemini' ? 'الوضع السحابي (Gemini)' : 'وضع أوفلاين (المحلي)';
    
    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                local_library_path: state.local_library_path,
                provider: nextProvider,
                embedding_provider: state.embedding_provider || 'local',
                gemini_api_key: state.gemini_api_key,
                lmstudio_url: state.lmstudio_url,
                lmstudio_model: state.lmstudio_model,
                ocr_enabled: state.ocr_enabled || false
            })
        });
        
        if (!response.ok) throw new Error();
        
        state.provider = nextProvider;
        updateHeaderStatus();
        updateSettingsModalFields(); // Sync settings modal UI too
        showToast(`تم التغيير إلى ${nextProviderLabel} بنجاح.`);
    } catch (err) {
        showToast("فشل التغيير السريع بين الأوضاع، يرجى المحاولة من الإعدادات.", true);
    }
}

// --- Client-side Routing (Tab Switching) ---

function setupRoutingHandlers() {
    menuItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId) {
    // Close sidebar on mobile if it is open
    const sidebar = document.querySelector('.sidebar');
    const menuToggle = document.getElementById('mobile-menu-toggle');
    if (sidebar && sidebar.classList.contains('open')) {
        sidebar.classList.remove('open');
        if (menuToggle) {
            const icon = menuToggle.querySelector('i');
            if (icon) icon.className = 'fa-solid fa-bars';
        }
    }

    // Update menu items
    menuItems.forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
    
    // Show/hide tab panels
    tabContents.forEach(content => {
        if (content.id === `tab-${tabId}`) {
            content.classList.add('active');
        } else {
            content.classList.remove('active');
        }
    });
    
    // Trigger lazy loading of database components
    if (tabId === 'legislation' && !state.legislationLoaded) {
        loadLegislation();
    } else if (tabId === 'rulings' && !state.rulingsLoaded) {
        loadRulings();
    } else if (tabId === 'templates' && !state.templatesLoaded) {
        loadTemplates();
    } else if (tabId === 'updates') {
        loadUpdates();
    }
}
window.switchTab = switchTab;

// --- Dashboard Logic ---

function setupDashboardQuickAsk() {
    quickAskBtn.addEventListener('click', () => {
        const query = quickAskInput.value.trim();
        if (!query) return;
        
        quickAskInput.value = '';
        
        // Transition to Chat tab
        switchTab('chat');
        
        // Fill chat input & send
        chatInput.value = query;
        handleSendMessage();
    });
    
    quickAskInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            quickAskBtn.click();
        }
    });
}

// --- Documents Library (Sync Center) ---

async function loadDocuments() {
    try {
        const response = await fetch('/api/documents');
        if (!response.ok) throw new Error();
        state.documents = await response.json();
        
        // Update stats
        statBooksCount.textContent = state.documents.length;
        
        renderDocuments();
    } catch (error) {
        showToast("فشل تحميل قائمة الكتب المؤرشفة.", true);
    }
}

function renderDocuments() {
    if (state.documents.length === 0) {
        docsList.innerHTML = `<div class="empty-docs">لا توجد كتب مؤرشفة حالياً. اضغط على مزامنة للبدء.</div>`;
        return;
    }
    
    docsList.innerHTML = state.documents.map(doc => `
        <div class="doc-item" id="doc-${doc.doc_id}">
            <div class="doc-info">
                <i class="fa-solid fa-file-pdf doc-file-icon"></i>
                <div class="doc-details">
                    <div class="doc-name" title="${doc.doc_name}">${doc.doc_name}</div>
                    <div class="doc-meta">${doc.pages_count} صفحة • ${doc.chunks_count} مادة</div>
                </div>
            </div>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-icon" onclick="viewPdfDocument('${doc.doc_id}')" title="تصفح وقراءة الكتاب" style="color: var(--secondary-color); background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.2); width: 32px; height: 32px; font-size: 14px;">
                    <i class="fa-solid fa-book-open"></i>
                </button>
                <button class="btn btn-icon btn-danger-icon" onclick="deleteDocument('${doc.doc_id}')" title="إزالة من قاعدة البيانات" style="width: 32px; height: 32px; font-size: 14px;">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        </div>
    `).join('');
}

async function deleteDocument(docId) {
    if (!confirm("هل أنت متأكد من إزالة هذا الكتاب من قاعدة البيانات؟ (لن يُحذف من مجلدك على الجهاز)")) return;
    try {
        const response = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error();
        
        state.documents = state.documents.filter(d => d.doc_id !== docId);
        renderDocuments();
        statBooksCount.textContent = state.documents.length;
        showToast("تم إزالة كتاب القانون من الفهرس وقاعدة البيانات.");
    } catch (error) {
        showToast("حدث خطأ أثناء محاولة حذف الفهرس.", true);
    }
}

function setupSyncHandlers() {
    syncLibraryBtn.addEventListener('click', handleLocalSync);
    // Check if sync is already running on page load
    checkActiveSyncStatus();
}

async function checkActiveSyncStatus() {
    try {
        const response = await fetch('/api/sync/status');
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'syncing') {
                startSyncPolling();
            }
        }
    } catch (e) {
        console.error("Failed to check active sync status:", e);
    }
}

async function handleLocalSync() {
    if (state.provider === 'gemini' && !state.gemini_api_key) {
        showToast("يُرجى إدخال مفتاح Gemini API أولاً في الإعدادات لتتمكن من قراءة الصور وتوليد المتجهات.", true);
        settingsModal.classList.add('active');
        return;
    }
    
    try {
        const response = await fetch('/api/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
            let errMsg = "فشلت عملية المزامنة.";
            try {
                const res = await response.json();
                if (res.error) errMsg = res.error;
            } catch(e) {}
            throw new Error(errMsg);
        }
        
        const data = await response.json();
        showToast(data.message);
        
        // Start polling real-time status
        startSyncPolling();
    } catch (error) {
        showToast(error.message, true);
    }
}

function startSyncPolling() {
    const icon = syncLibraryBtn.querySelector('.sync-icon');
    icon.classList.add('spinning');
    syncLibraryBtn.disabled = true;
    progressContainer.style.display = 'block';
    
    let lastProcessedCount = -1;
    
    // Select elements dynamically
    const statFile = document.getElementById('sync-stat-file');
    const statFilesRatio = document.getElementById('sync-stat-files-ratio');
    const statPagesRatio = document.getElementById('sync-stat-pages-ratio');
    const statSpeed = document.getElementById('sync-stat-speed');
    const statTime = document.getElementById('sync-stat-time');
    const syncConsole = document.getElementById('sync-console');
    const indicator = document.querySelector('.terminal-indicator');

    if (indicator) {
        indicator.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> فعال`;
        indicator.style.color = `var(--secondary-color)`;
    }

    const intervalId = setInterval(async () => {
        try {
            const response = await fetch('/api/sync/status');
            if (!response.ok) throw new Error();
            const data = await response.json();
            
            // Reload documents list live when a new file is completed
            if (data.processed_files !== lastProcessedCount) {
                lastProcessedCount = data.processed_files;
                loadDocuments();
            }
            
            // Update stats
            if (statFile) {
                statFile.textContent = data.current_file ? data.current_file : '-';
                statFile.title = data.current_file ? data.current_file : '';
            }
            if (statFilesRatio) statFilesRatio.textContent = `${data.processed_files} من ${data.total_files}`;
            if (statPagesRatio) statPagesRatio.textContent = `${data.current_page} من ${data.total_pages}`;
            if (statSpeed) statSpeed.textContent = `${data.pages_per_second} ص/ث`;
            if (statTime) statTime.textContent = `${data.elapsed_time.toFixed(1)} ثانية`;
            
            // Progress Bar Calculation
            let percent = 0;
            if (data.total_files > 0) {
                let filePercent = (data.processed_files / data.total_files) * 100;
                let pageContribution = 0;
                if (data.total_pages > 0 && data.current_page > 0) {
                    pageContribution = ((data.current_page / data.total_pages) * (1 / data.total_files)) * 100;
                }
                percent = Math.min(100, Math.round(filePercent + pageContribution));
            }
            if (progressBar) progressBar.style.width = `${percent}%`;
            
            // Action Text
            let actionText = "جاري المزامنة...";
            if (data.current_action === 'scanning') actionText = "جاري فحص المجلد المحلي للمكتبة...";
            else if (data.current_action === 'reading') actionText = `جاري قراءة ملف: ${data.current_file} (صفحة ${data.current_page}/${data.total_pages})`;
            else if (data.current_action === 'ocr') actionText = `جاري استخراج النص بالذكاء الاصطناعي (OCR) لصفحة ممسوحة ضوئياً...`;
            else if (data.current_action === 'embedding') actionText = `جاري إنشاء وتخزين التضمينات الفهرسية للملف...`;
            
            if (data.status === 'done') actionText = "اكتملت المزامنة بنجاح!";
            if (data.status === 'error') actionText = "حدث خطأ أثناء المزامنة.";
            if (progressText) progressText.textContent = actionText;
            
            // Terminal Logs Console
            if (syncConsole && data.logs) {
                // Add console logs with direction formatting for Arabic log messages
                syncConsole.innerHTML = data.logs.map(log => {
                    // Logs start with timestamp like [12:34:56]
                    let content = log.substring(11); // text after timestamp
                    let isArabic = /[\u0600-\u06FF]/.test(content);
                    let textDirection = isArabic ? 'rtl' : 'ltr';
                    let textAlign = isArabic ? 'right' : 'left';
                    return `<div style="direction: ${textDirection}; text-align: ${textAlign}; margin-bottom: 4px;">
                        <span style="color: #6B7280; font-family: monospace;">${log.substring(0, 10)}</span>
                        <span>${content}</span>
                    </div>`;
                }).join('');
                syncConsole.scrollTop = syncConsole.scrollHeight;
            }
            
            // Check status for completion
            if (data.status === 'done' || data.status === 'error' || data.status === 'idle') {
                clearInterval(intervalId);
                icon.classList.remove('spinning');
                syncLibraryBtn.disabled = false;
                
                if (indicator) {
                    if (data.status === 'done') {
                        indicator.innerHTML = `● مكتمل`;
                        indicator.style.color = `var(--success-color)`;
                        showToast("تمت مزامنة وفهرسة المكتبة القانونية بالكامل بنجاح!");
                    } else {
                        indicator.innerHTML = `● خطأ`;
                        indicator.style.color = `var(--error-color)`;
                        showToast("فشلت عملية المزامنة. يرجى التحقق من السجل لمعرفة التفاصيل.", true);
                    }
                }
                
                loadDocuments();
            }
        } catch (error) {
            console.error("Error polling sync status:", error);
        }
    }, 500);
}

// --- AI Chat Logic ---

async function saveChatSessionToServer(sessionId) {
    if (!sessionId) return;
    const sessionObj = chatSessions.find(s => s.id === sessionId);
    if (!sessionObj) return;
    
    try {
        await fetch('/api/chat/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sessionObj)
        });
        renderChatSessions();
    } catch (e) {
        console.error("Failed to save chat session: ", e);
    }
}

async function loadChatSessions() {
    try {
        const res = await fetch('/api/chat/history');
        if (!res.ok) return;
        chatSessions = await res.json();
        renderChatSessions();
        
        // Auto-select the last active chat session on load if none is selected
        if (chatSessions.length > 0 && !activeChatSessionId) {
            switchChatSession(chatSessions[0].id);
        }
    } catch (e) {
        console.error("Failed to load chat sessions: ", e);
    }
}

function renderChatSessions() {
    const listContainer = document.getElementById('sidebar-chat-list');
    if (!listContainer) return;
    
    // Toggle the display of the dashboard's "Resume last chat" shortcut
    const resumeContainer = document.getElementById('resume-chat-container');
    const resumeBtn = document.getElementById('resume-last-chat-btn');
    if (resumeContainer) {
        if (chatSessions.length > 0) {
            resumeContainer.style.display = 'block';
            if (resumeBtn) {
                const lastSessionTitle = chatSessions[0].title || "محادثة سابقة";
                resumeBtn.innerHTML = `<i class="fa-solid fa-clock-rotate-left"></i> استئناف المحادثة الأخيرة (${lastSessionTitle})...`;
                
                // Clone and replace to clean up previous event listeners
                const newResumeBtn = resumeBtn.cloneNode(true);
                resumeBtn.parentNode.replaceChild(newResumeBtn, resumeBtn);
                newResumeBtn.addEventListener('click', () => {
                    switchTab('chat');
                    if (chatSessions.length > 0) {
                        switchChatSession(chatSessions[0].id);
                    }
                });
            }
        } else {
            resumeContainer.style.display = 'none';
        }
    }
    
    if (chatSessions.length === 0) {
        listContainer.innerHTML = `<li style="color:var(--text-muted); font-size:11px; padding:8px; text-align:center;">لا توجد محادثات سابقة.</li>`;
        return;
    }
    
    listContainer.innerHTML = chatSessions.map(session => `
        <li class="sidebar-chat-item ${session.id === activeChatSessionId ? 'active' : ''}" data-session-id="${session.id}">
            <button class="chat-delete-btn" title="حذف الجلسة" style="background:none; border:none; color:#ef4444; cursor:pointer;"><i class="fa-solid fa-trash-can"></i></button>
            <span class="chat-title-span" title="${session.title}">${session.title}</span>
            <i class="fa-solid fa-comments" style="font-size: 11px;"></i>
        </li>
    `).join('');
    
    listContainer.querySelectorAll('.sidebar-chat-item').forEach(item => {
        const sessionId = item.getAttribute('data-session-id');
        item.addEventListener('click', (e) => {
            if (e.target.closest('.chat-delete-btn')) {
                e.stopPropagation();
                deleteChatSession(sessionId);
            } else {
                switchChatSession(sessionId);
            }
        });
    });
}

async function deleteChatSession(sessionId) {
    if (!confirm("هل تريد حذف هذه المحادثة؟")) return;
    try {
        const res = await fetch(`/api/chat/history/${sessionId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error();
        chatSessions = chatSessions.filter(s => s.id !== sessionId);
        if (activeChatSessionId === sessionId) {
            startNewChatSession();
        } else {
            renderChatSessions();
        }
        showToast("تم حذف المحادثة.");
    } catch (e) {
        showToast("فشل حذف المحادثة", true);
    }
}

function switchChatSession(sessionId) {
    activeChatSessionId = sessionId;
    renderChatSessions();
    
    const sessionObj = chatSessions.find(s => s.id === sessionId);
    if (!sessionObj) return;
    
    // Clear chat area
    messagesContainer.innerHTML = '';
    
    // Render session messages
    sessionObj.messages.forEach(msg => {
        if (msg.sources && msg.sources.length > 0) {
            state.currentChatSources[msg.id] = msg.sources;
        }
        appendMessage(msg.id, msg.role === 'user' ? 'user' : 'bot', msg.content, msg.sources || [], msg.voice);
    });
    
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function startNewChatSession() {
    activeChatSessionId = 'session-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    const welcome = messagesContainer.querySelector('.system-message');
    messagesContainer.innerHTML = '';
    if (welcome) messagesContainer.appendChild(welcome);
    
    chatSessions.unshift({
        id: activeChatSessionId,
        title: "محادثة جديدة",
        messages: [],
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000
    });
    
    renderChatSessions();
}

// --- AI Chat Logic ---

function setupChatHandlers() {
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        handleSendMessage();
    });
    
    clearChatBtn2.addEventListener('click', () => {
        if (activeChatSessionId) {
            deleteChatSession(activeChatSessionId);
        } else {
            const welcome = messagesContainer.querySelector('.system-message');
            messagesContainer.innerHTML = '';
            if (welcome) messagesContainer.appendChild(welcome);
            state.currentChatSources = {};
            closeSourcesSidebar();
        }
    });
    
    // Quick Suggestion Chips
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chatInput.value = chip.textContent;
            handleSendMessage();
        });
    });
}

async function handleSendMessage() {
    const query = chatInput.value.trim();
    if (!query) return;
    
    chatInput.value = '';
    
    if (!activeChatSessionId) {
        startNewChatSession();
    }
    
    const activeSession = chatSessions.find(s => s.id === activeChatSessionId);
    if (activeSession && (activeSession.title === "محادثة جديدة" || activeSession.messages.length === 0)) {
        activeSession.title = query.substring(0, 30) + (query.length > 30 ? '...' : '');
    }
    
    const userMsgId = 'msg-' + Date.now();
    appendMessage(userMsgId, 'user', query);
    
    if (activeSession) {
        activeSession.messages.push({
            id: userMsgId,
            role: 'user',
            content: query,
            timestamp: Date.now() / 1000
        });
    }
    
    const typingMsgId = 'typing-' + Date.now();
    appendTypingIndicator(typingMsgId);
    
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                query: query,
                voice: state.tts_voice
            })
        });
        
        removeTypingIndicator(typingMsgId);
        
        if (!response.ok) {
            let errMsg = "حدث خطأ في الخادم أثناء معالجة سؤالك.";
            try {
                const errJson = await response.json();
                if (errJson.error) errMsg = errJson.error;
            } catch(e) {}
            throw new Error(errMsg);
        }
        
        const data = await response.json();
        const botMsgId = 'msg-' + Date.now();
        
        state.currentChatSources[botMsgId] = data.sources || [];
        appendMessage(botMsgId, 'bot', data.answer, data.sources || [], data.voice);
        if (state.autoSpeak) {
            speakText(data.answer, 'ar-EG', data.voice);
        }
        
        if (activeSession) {
            activeSession.messages.push({
                id: botMsgId,
                role: 'assistant',
                content: data.answer,
                sources: data.sources || [],
                voice: data.voice,
                timestamp: Date.now() / 1000
            });
            saveChatSessionToServer(activeChatSessionId);
        }
    } catch (error) {
        removeTypingIndicator(typingMsgId);
        appendMessage('err-' + Date.now(), 'system', `⚠️ خطأ: ${error.message}`);
    }
    
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function appendMessage(msgId, sender, text, sources = [], voice = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${sender}-message`;
    msgDiv.id = msgId;
    
    const avatar = sender === 'user' ? 
        `<div class="message-avatar"><i class="fa-solid fa-user"></i></div>` : 
        `<div class="message-avatar"><i class="fa-solid fa-scale-balanced"></i></div>`;
        
    let bubbleContent = `<div class="message-bubble">${formatMarkdownText(text)}`;
    
    if (sender === 'bot') {
        bubbleContent += `
            <div class="message-actions" style="display:flex; justify-content:flex-end; margin-top:8px; gap:8px; border-top:1px solid rgba(255,255,255,0.03); padding-top:4px;">
                <button class="speak-msg-btn" data-msg-id="${msgId}" data-voice="${voice || ''}" title="استماع صوتي">
                    <i class="fa-solid fa-volume-high"></i> <span>استماع صوتي</span>
                </button>
            </div>
        `;
    }
    
    if (sender === 'bot' && sources.length > 0) {
        bubbleContent += `<div class="message-sources">
            <span>البنود والمواد المستند إليها:</span>
            ${sources.map(s => `
                <button class="citation-badge" onclick="viewSourceDetail('${msgId}', ${s.id})" title="كتاب: ${s.doc_name} • صفحة ${s.page}">
                    [المصدر ${s.id}]
                </button>
            `).join('')}
        </div>`;
    }
    bubbleContent += `</div>`;
    
    msgDiv.innerHTML = avatar + bubbleContent;
    messagesContainer.appendChild(msgDiv);
    
    if (sender === 'bot') {
        const btn = msgDiv.querySelector('.speak-msg-btn');
        if (btn) {
            btn.addEventListener('click', () => {
                try {
                    const customVoice = btn.getAttribute('data-voice');
                    speakText(text, 'ar-EG', customVoice || null);
                } catch (e) {
                    alert("Error playing audio: " + e.message);
                }
            });
        }
    }
}

function appendTypingIndicator(indicatorId) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message bot-message typing-indicator-msg`;
    msgDiv.id = indicatorId;
    
    msgDiv.innerHTML = `
        <div class="message-avatar"><i class="fa-solid fa-scale-balanced"></i></div>
        <div class="message-bubble" style="padding: 10px 18px;">
            <div class="typing-indicator">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        </div>
    `;
    messagesContainer.appendChild(msgDiv);
}

function removeTypingIndicator(indicatorId) {
    const indicator = document.getElementById(indicatorId);
    if (indicator) indicator.remove();
}

function formatMarkdownText(text) {
    if (!text) return "";
    let escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/\n/g, '<br>');
    return escaped;
}

// --- Sources Sidebar ---

function setupSourcesSidebarHandlers() {
    closeSourcesBtn.addEventListener('click', closeSourcesSidebar);
}

function closeSourcesSidebar() {
    sourcesSidebar.classList.remove('active');
}

window.viewPdfDocument = function(docId, pageNum = null) {
    let url = `/api/documents/view/${docId}`;
    if (pageNum) {
        url += `#page=${pageNum}`;
    }
    window.open(url, '_blank');
};

window.viewSourceDetail = function(messageId, sourceId) {
    const msgSources = state.currentChatSources[messageId];
    if (!msgSources) return;
    const source = msgSources.find(s => s.id === sourceId);
    if (!source) return;
    
    const doc = state.documents.find(d => d.doc_name === source.doc_name);
    const docId = doc ? doc.doc_id : null;
    
    let actionButton = '';
    if (docId) {
        actionButton = `
            <button class="btn btn-secondary btn-block" style="margin-top: 12px; font-size: 12px; gap: 6px; border-color: rgba(6, 182, 212, 0.3); color: var(--secondary-color); background: rgba(6, 182, 212, 0.05);" onclick="viewPdfDocument('${docId}', ${source.page})">
                <i class="fa-solid fa-book-open"></i> افتح الصفحة ${source.page} من هذا الكتاب
            </button>
        `;
    }
    
    sourcesContent.innerHTML = `
        <div class="source-card">
            <div class="source-card-header">
                <span class="source-badge-index">[المصدر ${source.id}]</span>
                <span class="source-meta-info">صفحة ${source.page}</span>
            </div>
            <h4 style="font-size: 13px; font-weight: 700; color: var(--text-main); line-height: 1.4;">
                <i class="fa-solid fa-book-open"></i> الكتاب: ${source.doc_name}
            </h4>
            <div class="source-text-block">
                ${source.text}
            </div>
            ${actionButton}
        </div>
    `;
    sourcesSidebar.classList.add('active');
};

// --- Legislation Tab Logic ---

function setupLegislationHandlers() {
    legislationSearchBtn.addEventListener('click', loadLegislation);
    legislationSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadLegislation();
    });
}

async function loadLegislation() {
    const search = legislationSearchInput.value.trim();
    const modeSelect = document.getElementById('legislation-search-mode');
    const searchMode = modeSelect ? modeSelect.value : 'local';
    
    legislationListContainer.innerHTML = '<div class="loading-spinner">جاري البحث في مواد القوانين...</div>';
    
    try {
        if (searchMode === 'ai' && search) {
            const response = await fetch('/api/semantic-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: search, type: 'legislation', mode: 'ai' })
            });
            if (!response.ok) throw new Error();
            const data = await response.json();
            state.legislationLoaded = true;
            renderSemanticResults(data.matches || [], legislationListContainer);
        } else {
            const response = await fetch(`/api/legislation?search=${encodeURIComponent(search)}`);
            if (!response.ok) throw new Error();
            const laws = await response.json();
            state.legislationLoaded = true;
            renderLegislation(laws, !!search);
        }
    } catch (error) {
        legislationListContainer.innerHTML = '<div style="color:#EF4444; padding:20px; text-align:center;">حدث خطأ أثناء تحميل موسوعة التشريعات.</div>';
    }
}

function renderSemanticResults(matches, container) {
    if (matches.length === 0) {
        container.innerHTML = '<div style="color:var(--text-muted); padding:30px; text-align:center;">لم يتم العثور على أي نتائج مطابقة للبحث بالمعنى.</div>';
        return;
    }
    
    container.innerHTML = matches.map(m => `
        <div class="law-card semantic-match-card">
            <div class="law-card-header" style="border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 12px;">
                <h3 style="display: flex; align-items: center; gap: 8px;">
                    <span class="badge" style="background: rgba(14, 165, 233, 0.15); color: var(--primary); border: 1px solid var(--primary); font-size: 11px; padding: 3px 6px;">
                        <i class="fa-solid fa-brain"></i> ${m.source}
                    </span>
                    ${m.title}
                </h3>
            </div>
            <div class="semantic-match-body">
                <p style="white-space: pre-wrap; font-size: 0.95rem; line-height: 1.6; color: var(--text-main); margin-bottom: 12px;">${m.details}</p>
            </div>
            ${m.relevance ? `
                <div class="relevance-box" style="background: rgba(34, 197, 94, 0.08); border-right: 3px solid #22c55e; padding: 10px; border-radius: 4px; font-size: 13px; margin-top: 8px;">
                    <strong style="color: #22c55e; margin-left: 5px;"><i class="fa-solid fa-circle-check"></i> سبب التطابق الدلالي:</strong>
                    <span style="color: var(--text-muted);">${m.relevance}</span>
                </div>
            ` : ''}
        </div>
    `).join('');
}

function renderLegislation(laws, isSearched) {
    if (laws.length === 0) {
        legislationListContainer.innerHTML = '<div style="color:var(--text-muted); padding:30px; text-align:center;">لم يتم العثور على أي تشريعات أو مواد قانونية تطابق شروط البحث.</div>';
        return;
    }
    
    legislationListContainer.innerHTML = laws.map(law => `
        <div class="law-card">
            <div class="law-card-header">
                <h3><i class="fa-solid fa-scale-unbalanced-flip"></i> ${law.name}</h3>
                ${!isSearched ? `<span class="badge" style="background:rgba(6, 182, 212, 0.1); border-color:var(--secondary-color); color:var(--secondary-color);">${law.articles_count} مادة</span>` : ''}
            </div>
            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">${law.description}</p>
            ${isSearched && law.articles ? `
                <div class="articles-list">
                    ${law.articles.map(art => `
                        <div class="article-item">
                            <strong>المادة رقم ${art.num || art.number}</strong>
                            <p>${art.text}</p>
                        </div>
                    `).join('')}
                </div>
            ` : `
                <button class="btn btn-secondary btn-block" onclick="viewAllArticles('${law.id}')">تصفح مواد ${law.name}</button>
            `}
        </div>
    `).join('');
}

window.viewAllArticles = async function(lawId) {
    legislationListContainer.innerHTML = '<div class="loading-spinner">جاري تحميل المواد...</div>';
    try {
        const response = await fetch('/api/legislation');
        if (!response.ok) throw new Error();
        const laws = await response.json();
        
        // Find specific law
        const searchRes = await fetch(`/api/legislation?search=`);
        const fullLaws = await searchRes.json();
        const targetLaw = fullLaws.find(l => l.id === lawId);
        
        if (targetLaw) {
            legislationListContainer.innerHTML = `
                <button class="btn btn-secondary" style="margin-bottom:16px;" onclick="loadLegislation()"><i class="fa-solid fa-arrow-right"></i> العودة للموسوعة</button>
                <div class="law-card">
                    <div class="law-card-header">
                        <h3><i class="fa-solid fa-scale-unbalanced-flip"></i> ${targetLaw.name}</h3>
                    </div>
                    <div class="articles-list">
                        ${targetLaw.articles.map(art => `
                            <div class="article-item">
                                <strong>المادة رقم ${art.num}</strong>
                                <p>${art.text}</p>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
    } catch (e) {
        showToast("فشل فتح مواد القانون.", true);
    }
};

// --- Court Rulings Tab Logic ---

function setupRulingsHandlers() {
    rulingSearchBtn.addEventListener('click', loadRulings);
    rulingSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadRulings();
    });
    rulingCategorySelect.addEventListener('change', loadRulings);
}

async function loadRulings() {
    const search = rulingSearchInput.value.trim();
    const category = rulingCategorySelect.value;
    const modeSelect = document.getElementById('ruling-search-mode');
    const searchMode = modeSelect ? modeSelect.value : 'local';
    
    rulingsListContainer.innerHTML = '<div class="loading-spinner">جاري البحث في أرشيف أحكام محكمة النقض...</div>';
    
    try {
        if (searchMode === 'ai' && search) {
            const response = await fetch('/api/semantic-search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: search, type: 'rulings', mode: 'ai' })
            });
            if (!response.ok) throw new Error();
            const data = await response.json();
            
            // Filter by category if selected
            let matches = data.matches || [];
            if (category) {
                matches = matches.filter(m => m.title.includes(category) || m.details.includes(category));
            }
            
            state.rulingsLoaded = true;
            renderSemanticResults(matches, rulingsListContainer);
        } else {
            const response = await fetch(`/api/rulings?search=${encodeURIComponent(search)}&category=${encodeURIComponent(category)}`);
            if (!response.ok) throw new Error();
            const rulings = await response.json();
            
            state.rulingsLoaded = true;
            renderRulings(rulings);
        }
    } catch (error) {
        rulingsListContainer.innerHTML = '<div style="color:#EF4444; padding:20px; text-align:center;">حدث خطأ أثناء تحميل أحكام محكمة النقض.</div>';
    }
}

function renderRulings(rulings) {
    if (rulings.length === 0) {
        rulingsListContainer.innerHTML = '<div style="color:var(--text-muted); padding:30px; text-align:center;">لم يتم العثور على أي أحكام قضائية تطابق البحث.</div>';
        return;
    }
    
    rulingsListContainer.innerHTML = rulings.map(r => `
        <div class="ruling-card">
            <div class="ruling-header">
                <span class="ruling-case-num">${r.case_num}</span>
                <span class="ruling-meta">${r.court} • ${r.date}</span>
            </div>
            <div class="ruling-principle">المبدأ: ${r.principle}</div>
            <div class="ruling-details">${r.details}</div>
        </div>
    `).join('');
}

// --- Templates & Contracts Tab Logic ---

function setupTemplatesHandlers() {
    copyTemplateBtn.addEventListener('click', handleCopyTemplate);
}

async function loadTemplates() {
    templatesListContainer.innerHTML = '<div class="loading-spinner">جاري تحميل الصيغ...</div>';
    
    try {
        const response = await fetch('/api/templates');
        if (!response.ok) throw new Error();
        state.templates = await response.json();
        state.templatesLoaded = true;
        
        renderTemplatesMenu();
    } catch (error) {
        templatesListContainer.innerHTML = '<div style="color:#EF4444; padding:20px; text-align:center;">حدث خطأ أثناء تحميل صيغ العقود.</div>';
    }
}

function renderTemplatesMenu() {
    // Group templates by category
    const categories = {};
    state.templates.forEach(t => {
        if (!categories[t.category]) {
            categories[t.category] = [];
        }
        categories[t.category].push(t);
    });
    
    let html = '';
    for (const [catName, list] of Object.entries(categories)) {
        html += `
            <div class="template-category-group">
                <h4><i class="fa-solid fa-folder"></i> ${catName}</h4>
                <ul>
                    ${list.map(t => `
                        <li class="template-item ${state.activeTemplateId === t.id ? 'active' : ''}" onclick="selectTemplate('${t.id}')">
                            ${t.title}
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }
    
    templatesListContainer.innerHTML = html;
}

window.selectTemplate = function(templateId) {
    state.activeTemplateId = templateId;
    renderTemplatesMenu(); // Re-render to update active state class
    
    const template = state.templates.find(t => t.id === templateId);
    if (!template) return;
    
    activeTemplateTitle.textContent = template.title;
    templateEditorTextarea.value = template.content;
    
    // Enable controls
    templateEditorTextarea.disabled = false;
    copyTemplateBtn.disabled = false;
};

function handleCopyTemplate() {
    const content = templateEditorTextarea.value;
    if (!content) return;
    
    navigator.clipboard.writeText(content)
        .then(() => {
            showToast("تم نسخ نص الصيغة بالكامل للحافظة بنجاح!");
        })
        .catch(err => {
            showToast("فشل في نسخ النص تلقائياً، يرجى تظليله ونسخه يدوياً.", true);
        });
}

// --- Settings Modal Logic ---

function setupSettingsModalHandlers() {
    settingsTrigger.addEventListener('click', () => {
        updateSettingsModalFields();
        settingsModal.classList.add('active');
    });
    
    const closeModal = () => settingsModal.classList.remove('active');
    
    closeSettingsBtn.addEventListener('click', closeModal);
    cancelSettingsBtn.addEventListener('click', closeModal);
    
    providerSelect.addEventListener('change', (e) => {
        toggleConfigSections(e.target.value);
    });
    
    toggleApiKeyVisBtn.addEventListener('click', () => {
        const type = geminiApiKeyInput.type === 'password' ? 'text' : 'password';
        geminiApiKeyInput.type = type;
        toggleApiKeyVisBtn.innerHTML = type === 'password' ? 
            `<i class="fa-solid fa-eye"></i>` : `<i class="fa-solid fa-eye-slash"></i>`;
    });
    
    saveSettingsBtn.addEventListener('click', async () => {
        const local_library_path = libraryPathInput.value.trim();
        const provider = providerSelect.value;
        const embedProviderSelect = document.getElementById('embed-provider-select');
        const embedding_provider = embedProviderSelect ? embedProviderSelect.value : 'local';
        const gemini_api_key = geminiApiKeyInput.value.trim();
        const lmstudio_url = lmstudioUrlInput.value.trim();
        const lmstudio_model = lmstudioModelInput.value.trim();
        const ocr_enabled = ocrEnabledCheckbox.checked;
        
        if (!local_library_path) {
            showToast("يُرجى إدخال مسار مجلد الكتب القانونية على جهازك.", true);
            return;
        }
        
        if (provider === 'gemini' && !gemini_api_key) {
            showToast("يُرجى إدخال مفتاح Gemini API الخاص بك.", true);
            return;
        }
        
        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    local_library_path,
                    provider,
                    embedding_provider,
                    gemini_api_key,
                    lmstudio_url,
                    lmstudio_model,
                    ocr_enabled
                })
            });
            
            if (!response.ok) throw new Error();
            
            state.local_library_path = local_library_path;
            state.provider = provider;
            state.embedding_provider = embedding_provider;
            state.gemini_api_key = gemini_api_key;
            state.lmstudio_url = lmstudio_url;
            state.lmstudio_model = lmstudio_model;
            state.ocr_enabled = ocr_enabled;
            
            // Save Voice settings locally
            const ttsVoiceSelect = document.getElementById('tts-voice-select');
            const ttsRateSelect = document.getElementById('tts-rate-select');
            if (ttsVoiceSelect) {
                state.tts_voice = ttsVoiceSelect.value;
                localStorage.setItem('tts_voice', state.tts_voice);
            }
            if (ttsRateSelect) {
                state.tts_rate = ttsRateSelect.value;
                localStorage.setItem('tts_rate', state.tts_rate);
            }
            
            closeModal();
            updateHeaderStatus();
            
            // Update UI elements displaying the path
            sidebarPathLabel.textContent = local_library_path;
            sidebarPathLabel.title = local_library_path;
            syncLibraryPathLabel.textContent = local_library_path;
            
            showToast("تم حفظ الإعدادات وتحديث المكتبة ومزود الذكاء الاصطناعي.");
            loadDocuments();
        } catch (error) {
            showToast("فشل حفظ الإعدادات على الخادم.", true);
        }
    });
}

// ============================================================
// CONTRACT BUILDER
// ============================================================

function initContractBuilder() {
    const generateBtn = document.getElementById('cb-generate-btn');
    const copyBtn = document.getElementById('cb-copy-btn');
    const printBtn = document.getElementById('cb-print-btn');
    const outputArea = document.getElementById('cb-output-area');

    if (!generateBtn) return;

    generateBtn.addEventListener('click', async () => {
        const contractType = document.getElementById('cb-contract-type').value;
        if (!contractType) {
            showToast('يُرجى اختيار نوع العقد أولاً.', true);
            return;
        }

        generateBtn.disabled = true;
        generateBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري إنشاء العقد...';
        outputArea.innerHTML = '<div class="ai-loading-box"><div class="ai-loader-dots"><span></span><span></span><span></span></div><p>الذكاء الاصطناعي يصوغ العقد بصياغة قانونية احترافية...</p></div>';
        copyBtn.disabled = true;
        if (printBtn) printBtn.disabled = true;

        const fields = {
            'الطرف الأول': document.getElementById('cb-party1').value,
            'الرقم القومي / السجل الطرف الأول': document.getElementById('cb-party1-id').value,
            'الطرف الثاني': document.getElementById('cb-party2').value,
            'الرقم القومي / السجل الطرف الثاني': document.getElementById('cb-party2-id').value,
            'موضوع العقد': document.getElementById('cb-subject').value,
            'القيمة المالية': document.getElementById('cb-amount').value,
            'تاريخ الابتداء': document.getElementById('cb-start-date').value,
            'تاريخ الانتهاء': document.getElementById('cb-end-date').value,
            'شروط خاصة': document.getElementById('cb-special-terms').value,
        };

        try {
            const res = await fetch('/api/contracts/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ contract_type: contractType, fields })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            // Render contract with markdown-like formatting
            const html = renderMarkdown(data.contract);
            outputArea.innerHTML = `<div class="contract-text">${html}</div>`;
            copyBtn.disabled = false;
            copyBtn._contractText = data.contract;
            if (printBtn) printBtn.disabled = false;
            showToast('تم إنشاء العقد بنجاح!');
        } catch (e) {
            outputArea.innerHTML = `<div class="error-box"><i class="fa-solid fa-triangle-exclamation"></i> ${e.message}</div>`;
            showToast(e.message, true);
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> أنشئ العقد بالذكاء الاصطناعي';
        }
    });

    copyBtn.addEventListener('click', () => {
        if (copyBtn._contractText) {
            navigator.clipboard.writeText(copyBtn._contractText);
            showToast('تم نسخ العقد كاملاً إلى الحافظة.');
        }
    });

    if (printBtn) {
        printBtn.addEventListener('click', () => {
            printContent(outputArea.innerHTML, 'عقد قانوني - بوابة القانون');
        });
    }
}

// ============================================================
// DOCUMENT ANALYZER
// ============================================================

function initAnalyzer() {
    const analyzerBtn = document.getElementById('analyzer-btn');
    const copyBtn = document.getElementById('analyzer-copy-btn');
    const printBtn = document.getElementById('analyzer-print-btn');
    const outputArea = document.getElementById('analyzer-output-area');
    const fileInput = document.getElementById('analyzer-file-input');
    const browseBtn = document.getElementById('analyzer-browse-btn');
    const dropZone = document.getElementById('analyzer-drop-zone');
    const fileNameDisplay = document.getElementById('analyzer-file-name');

    if (!analyzerBtn) return;

    let selectedFile = null;

    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        selectedFile = e.target.files[0];
        if (selectedFile) {
            fileNameDisplay.textContent = `✅ تم اختيار: ${selectedFile.name}`;
            fileNameDisplay.style.color = '#4ade80';
        }
    });

    // Drag & drop support
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-active');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-active'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-active');
        const f = e.dataTransfer.files[0];
        if (f && f.name.toLowerCase().endsWith('.pdf')) {
            selectedFile = f;
            fileNameDisplay.textContent = `✅ تم اختيار: ${f.name}`;
            fileNameDisplay.style.color = '#4ade80';
        } else {
            showToast('يُرجى إسقاط ملف PDF فقط.', true);
        }
    });

    analyzerBtn.addEventListener('click', async () => {
        const textInput = document.getElementById('analyzer-text-input').value.trim();

        if (!selectedFile && !textInput) {
            showToast('يُرجى رفع ملف PDF أو إدخال نص المستند.', true);
            return;
        }

        analyzerBtn.disabled = true;
        analyzerBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري التحليل...';
        outputArea.innerHTML = '<div class="ai-loading-box"><div class="ai-loader-dots"><span></span><span></span><span></span></div><p>الذكاء الاصطناعي يحلل المستند ويعدّ التقرير القانوني...</p></div>';
        copyBtn.disabled = true;
        if (printBtn) printBtn.disabled = true;

        try {
            let res;
            if (selectedFile) {
                const formData = new FormData();
                formData.append('file', selectedFile);
                res = await fetch('/api/analyze', { method: 'POST', body: formData });
            } else {
                res = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: textInput })
                });
            }

            const data = await res.json();
            if (data.error) throw new Error(data.error);

            const html = renderMarkdown(data.analysis);
            outputArea.innerHTML = `<div class="contract-text">${html}</div>`;
            copyBtn.disabled = false;
            copyBtn._analysisText = data.analysis;
            if (printBtn) printBtn.disabled = false;
            showToast('اكتمل التحليل القانوني!');
        } catch (e) {
            outputArea.innerHTML = `<div class="error-box"><i class="fa-solid fa-triangle-exclamation"></i> ${e.message}</div>`;
            showToast(e.message, true);
        } finally {
            analyzerBtn.disabled = false;
            analyzerBtn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> حلّل المستند الآن';
        }
    });

    copyBtn.addEventListener('click', () => {
        if (copyBtn._analysisText) {
            navigator.clipboard.writeText(copyBtn._analysisText);
            showToast('تم نسخ التحليل إلى الحافظة.');
        }
    });

    if (printBtn) {
        printBtn.addEventListener('click', () => {
            printContent(outputArea.innerHTML, 'التقرير والتحليل القانوني - بوابة القانون');
        });
    }
}

// ============================================================
// CASE MANAGER
// ============================================================

let casesData = [];

function initCaseManager() {
    const addBtn = document.getElementById('cases-add-btn');
    const modal = document.getElementById('case-modal');
    const closeModalBtn = document.getElementById('close-case-modal-btn');
    const cancelBtn = document.getElementById('cancel-case-modal-btn');
    const saveBtn = document.getElementById('save-case-btn');

    if (!addBtn) return;

    loadCases();

    addBtn.addEventListener('click', () => openCaseModal());
    closeModalBtn.addEventListener('click', () => closeCaseModal());
    cancelBtn.addEventListener('click', () => closeCaseModal());

    saveBtn.addEventListener('click', async () => {
        const clientName = document.getElementById('case-client-name').value.trim();
        const caseNumber = document.getElementById('case-number').value.trim();
        if (!clientName || !caseNumber) {
            showToast('يُرجى إدخال اسم الموكل ورقم القضية على الأقل.', true);
            return;
        }

        const editId = document.getElementById('case-edit-id').value;
        const caseData = {
            client_name: clientName,
            client_phone: document.getElementById('case-client-phone').value,
            client_id: document.getElementById('case-client-id').value,
            case_number: caseNumber,
            court: document.getElementById('case-court').value,
            case_type: document.getElementById('case-type').value,
            status: document.getElementById('case-status').value,
            next_session: document.getElementById('case-next-session').value,
            notes: document.getElementById('case-notes').value,
        };

        try {
            let res;
            if (editId) {
                res = await fetch(`/api/cases/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(caseData)
                });
            } else {
                res = await fetch('/api/cases', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(caseData)
                });
            }
            if (!res.ok) throw new Error();
            closeCaseModal();
            loadCases();
            showToast(editId ? 'تم تحديث القضية.' : 'تمت إضافة القضية بنجاح!');
        } catch {
            showToast('فشل حفظ القضية.', true);
        }
    });
}

async function loadCases() {
    try {
        const res = await fetch('/api/cases');
        casesData = await res.json();
        renderCasesTable();
    } catch {
        casesData = [];
    }
}

function renderCasesTable() {
    const tbody = document.getElementById('cases-tbody');
    if (!tbody) return;

    // Update stats
    document.getElementById('cs-total').textContent = casesData.length;
    document.getElementById('cs-active').textContent = casesData.filter(c => c.status === 'نشطة').length;
    document.getElementById('cs-pending').textContent = casesData.filter(c => c.status === 'معلّقة').length;
    document.getElementById('cs-closed').textContent = casesData.filter(c => c.status === 'مغلقة').length;

    if (casesData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-table-msg">لا توجد قضايا مسجلة. اضغط "قضية جديدة" للبدء.</td></tr>';
        return;
    }

    tbody.innerHTML = casesData.map(c => {
        const statusClass = c.status === 'نشطة' ? 'status-active' : c.status === 'معلّقة' ? 'status-pending' : 'status-closed';
        const sessionDate = c.next_session ? new Date(c.next_session).toLocaleDateString('ar-EG') : '—';
        return `
        <tr>
            <td><strong>${c.client_name}</strong><br><small style="color:var(--text-muted)">${c.client_phone || ''}</small></td>
            <td>${c.case_number}</td>
            <td>${c.court || '—'}</td>
            <td><span class="case-type-badge">${c.case_type}</span></td>
            <td><span class="case-status ${statusClass}">${c.status}</span></td>
            <td>${sessionDate}</td>
            <td>
                <button class="btn btn-icon" title="تعديل" onclick="openCaseModal('${c.id}')"><i class="fa-solid fa-pen"></i></button>
                <button class="btn btn-icon btn-danger-icon" title="حذف" onclick="deleteCase('${c.id}')"><i class="fa-solid fa-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
}

function openCaseModal(caseId = null) {
    const modal = document.getElementById('case-modal');
    const title = document.getElementById('case-modal-title');
    document.getElementById('case-edit-id').value = '';
    ['case-client-name','case-client-phone','case-client-id','case-number','case-court','case-notes','case-next-session'].forEach(id => {
        document.getElementById(id).value = '';
    });
    document.getElementById('case-type').value = 'مدني';
    document.getElementById('case-status').value = 'نشطة';

    if (caseId) {
        const c = casesData.find(x => x.id === caseId);
        if (c) {
            title.innerHTML = '<i class="fa-solid fa-pen"></i> تعديل القضية';
            document.getElementById('case-edit-id').value = c.id;
            document.getElementById('case-client-name').value = c.client_name;
            document.getElementById('case-client-phone').value = c.client_phone;
            document.getElementById('case-client-id').value = c.client_id;
            document.getElementById('case-number').value = c.case_number;
            document.getElementById('case-court').value = c.court;
            document.getElementById('case-notes').value = c.notes;
            document.getElementById('case-next-session').value = c.next_session;
            document.getElementById('case-type').value = c.case_type;
            document.getElementById('case-status').value = c.status;
        }
    } else {
        title.innerHTML = '<i class="fa-solid fa-briefcase"></i> إضافة قضية جديدة';
    }

    modal.style.display = 'flex';
}

function closeCaseModal() {
    document.getElementById('case-modal').style.display = 'none';
}

async function deleteCase(caseId) {
    if (!confirm('هل أنت متأكد من حذف هذه القضية؟')) return;
    try {
        await fetch(`/api/cases/${caseId}`, { method: 'DELETE' });
        loadCases();
        showToast('تم حذف القضية.');
    } catch {
        showToast('فشل حذف القضية.', true);
    }
}

// ============================================================
// DEADLINE CALCULATOR (Pure JS — No API needed)
// ============================================================

function initCalculator() {
    const limitationBtn = document.getElementById('calc-limitation-btn');
    const appealBtn = document.getElementById('calc-appeal-btn');
    const laborBtn = document.getElementById('calc-labor-btn');
    const diffBtn = document.getElementById('calc-diff-btn');
    if (!limitationBtn) return;

    // Statute of limitations
    limitationBtn.addEventListener('click', () => {
        const years = parseInt(document.getElementById('calc-limitation-type').value);
        const startDate = document.getElementById('calc-limitation-start').value;
        const result = document.getElementById('calc-limitation-result');
        if (!startDate) { result.innerHTML = '<span class="calc-error">يُرجى اختيار تاريخ نشأة الحق.</span>'; return; }
        const start = new Date(startDate);
        const end = new Date(start);
        end.setFullYear(end.getFullYear() + years);
        const today = new Date();
        const isExpired = today > end;
        const daysLeft = Math.ceil((end - today) / (1000 * 60 * 60 * 24));
        result.innerHTML = `
            <div class="calc-result-box ${isExpired ? 'expired' : 'valid'}">
                <div class="calc-result-icon">${isExpired ? '❌' : '✅'}</div>
                <div>
                    <strong>آخر موعد للتقادم:</strong> ${end.toLocaleDateString('ar-EG')}<br>
                    ${isExpired
                        ? `<span style="color:#f87171;">⚠️ انقضى التقادم منذ ${Math.abs(daysLeft)} يوم</span>`
                        : `<span style="color:#4ade80;">✔ لا يزال أمامك <strong>${daysLeft}</strong> يوم</span>`}
                </div>
            </div>`;
    });

    // Appeal deadlines
    appealBtn.addEventListener('click', () => {
        const days = parseInt(document.getElementById('calc-appeal-type').value);
        const ruling = document.getElementById('calc-appeal-date').value;
        const result = document.getElementById('calc-appeal-result');
        if (!ruling) { result.innerHTML = '<span class="calc-error">يُرجى اختيار تاريخ الحكم.</span>'; return; }
        const start = new Date(ruling);
        const end = new Date(start);
        end.setDate(end.getDate() + days);
        const today = new Date();
        const isExpired = today > end;
        const daysLeft = Math.ceil((end - today) / (1000 * 60 * 60 * 24));
        result.innerHTML = `
            <div class="calc-result-box ${isExpired ? 'expired' : 'valid'}">
                <div class="calc-result-icon">${isExpired ? '❌' : '✅'}</div>
                <div>
                    <strong>آخر موعد للطعن:</strong> ${end.toLocaleDateString('ar-EG')}<br>
                    ${isExpired
                        ? `<span style="color:#f87171;">⚠️ انقضى ميعاد الطعن منذ ${Math.abs(daysLeft)} يوم</span>`
                        : `<span style="color:#4ade80;">✔ لا يزال أمامك <strong>${daysLeft}</strong> يوم للطعن</span>`}
                </div>
            </div>`;
    });

    // Labor notice period
    laborBtn.addEventListener('click', () => {
        const days = parseInt(document.getElementById('calc-labor-tenure').value);
        const noticeDate = document.getElementById('calc-labor-date').value;
        const result = document.getElementById('calc-labor-result');
        if (!noticeDate) { result.innerHTML = '<span class="calc-error">يُرجى اختيار تاريخ الإخطار.</span>'; return; }
        const start = new Date(noticeDate);
        const end = new Date(start);
        end.setDate(end.getDate() + days);
        result.innerHTML = `
            <div class="calc-result-box valid">
                <div class="calc-result-icon">📅</div>
                <div>
                    <strong>آخر يوم في العمل:</strong> ${end.toLocaleDateString('ar-EG')}<br>
                    <span style="color:#94a3b8;">مدة الإخطار: ${days} يوماً من تاريخ الإخطار</span>
                </div>
            </div>`;
    });

    // Days between two dates
    diffBtn.addEventListener('click', () => {
        const start = document.getElementById('calc-diff-start').value;
        const end = document.getElementById('calc-diff-end').value;
        const result = document.getElementById('calc-diff-result');
        if (!start || !end) { result.innerHTML = '<span class="calc-error">يُرجى اختيار تاريخ البداية والنهاية.</span>'; return; }
        const d1 = new Date(start);
        const d2 = new Date(end);
        const diff = Math.abs(Math.ceil((d2 - d1) / (1000 * 60 * 60 * 24)));
        const months = Math.floor(diff / 30);
        const years = Math.floor(diff / 365);
        result.innerHTML = `
            <div class="calc-result-box valid">
                <div class="calc-result-icon">🗓️</div>
                <div>
                    <strong>الفرق الزمني:</strong><br>
                    <span style="font-size:1.4rem; font-weight:700; color:var(--accent-blue);">${diff} يوم</span><br>
                    <span style="color:#94a3b8;">≈ ${months} شهر / ${years} سنة</span>
                </div>
            </div>`;
    });
}

// ============================================================
// Shared markdown-like renderer
// ============================================================
function renderMarkdown(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^#{1,3} (.+)$/gm, '<h3 style="color:var(--accent-blue);margin:16px 0 8px;">$1</h3>')
        .replace(/^(\d+)\. (.+)$/gm, '<div class="contract-list-item"><span class="contract-item-num">$1</span> $2</div>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
}

// ============================================================
// PDF Print Helper
// ============================================================
function printContent(htmlContent, title) {
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <title>${title}</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
                body {
                    font-family: 'Cairo', sans-serif;
                    padding: 40px;
                    color: #1e293b;
                    line-height: 1.8;
                    background: #fff;
                    font-size: 14pt;
                }
                .print-header {
                    text-align: center;
                    border-bottom: 2px solid #0284c7;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                }
                .print-header h1 {
                    margin: 0;
                    font-size: 24pt;
                    color: #0284c7;
                }
                .print-header p {
                    margin: 5px 0 0 0;
                    color: #64748b;
                    font-size: 11pt;
                }
                .content-area {
                    margin-bottom: 40px;
                }
                .content-area p {
                    margin-bottom: 1.5em;
                    text-align: justify;
                }
                .print-footer {
                    text-align: center;
                    border-top: 1px solid #e2e8f0;
                    padding-top: 20px;
                    margin-top: 50px;
                    color: #94a3b8;
                    font-size: 10pt;
                }
                @media print {
                    body {
                        padding: 0;
                    }
                    @page {
                        margin: 20mm;
                    }
                }
            </style>
        </head>
        <body>
            <div class="print-header">
                <h1>بوابة القانون الذكية</h1>
                <p>${title}</p>
            </div>
            <div class="content-area">
                ${htmlContent}
            </div>
            <div class="print-footer">
                تم الإنشاء بواسطة بوابة القانون الذكية المتكاملة (AI)
            </div>
            <script>
                window.onload = function() {
                    window.print();
                    setTimeout(() => window.close(), 100);
                }
            </script>
        </body>
        </html>
    `);
    printWindow.document.close();
}

// ============================================================
// Text Comparison Logic
// ============================================================
function initCompare() {
    const compareSubmitBtn = document.getElementById('compare-submit-btn');
    const compareText1 = document.getElementById('compare-text-1');
    const compareText2 = document.getElementById('compare-text-2');
    const compareAiAnalysis = document.getElementById('compare-ai-analysis');
    const compareResultsArea = document.getElementById('compare-results-area');
    const diffVisualOutput = document.getElementById('diff-visual-output');
    const compareAiAnalysisBlock = document.getElementById('compare-ai-analysis-block');
    const compareAiOutput = document.getElementById('compare-ai-output');

    if (!compareSubmitBtn) return;

    compareSubmitBtn.addEventListener('click', async () => {
        const text1 = compareText1.value.trim();
        const text2 = compareText2.value.trim();
        const useAi = compareAiAnalysis.checked;

        if (!text1 || !text2) {
            showToast("يُرجى إدخال النص الأصلي والنص المعدل للمقارنة.", true);
            return;
        }

        compareSubmitBtn.disabled = true;
        compareSubmitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري المقارنة والتحليل...';
        compareResultsArea.style.display = 'none';

        try {
            const response = await fetch('/api/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text1: text1, text2: text2, analyze: useAi })
            });

            if (!response.ok) throw new Error();
            const data = await response.json();

            // Render visual diff
            diffVisualOutput.innerHTML = '';
            if (data.diff && data.diff.length > 0) {
                diffVisualOutput.innerHTML = data.diff.map(block => {
                    const cleanText = block.text.replace(/\n/g, '<br>');
                    if (block.type === 'equal') {
                        return `<span class="diff-equal">${cleanText}</span>`;
                    } else if (block.type === 'delete') {
                        return `<span class="diff-delete">${cleanText}</span>`;
                    } else if (block.type === 'insert') {
                        return `<span class="diff-insert">${cleanText}</span>`;
                    }
                    return '';
                }).join('');
            } else {
                diffVisualOutput.innerHTML = '<div style="color:var(--text-muted);">لا توجد فروقات لفظية بين النصين.</div>';
            }

            // Render AI Analysis
            if (useAi) {
                compareAiAnalysisBlock.style.display = 'block';
                compareAiOutput.innerHTML = renderMarkdown(data.analysis || 'لا يوجد تحليل متوفر.');
            } else {
                compareAiAnalysisBlock.style.display = 'none';
            }

            compareResultsArea.style.display = 'block';
            showToast("تمت مقارنة النصوص بنجاح.");
        } catch (error) {
            showToast("حدث خطأ أثناء مقارنة النصوص.", true);
        } finally {
            compareSubmitBtn.disabled = false;
            compareSubmitBtn.innerHTML = '<i class="fa-solid fa-code-compare"></i> بدء المقارنة';
        }
    });
}

// ============================================================
// Legal Translation Logic
// ============================================================
function initTranslate() {
    const translateSubmitBtn = document.getElementById('translate-submit-btn');
    const translateInputText = document.getElementById('translate-input-text');
    const translationDirection = document.getElementById('translation-direction');
    const translateOutputText = document.getElementById('translate-output-text');

    if (!translateSubmitBtn) return;

    translateSubmitBtn.addEventListener('click', async () => {
        const text = translateInputText.value.trim();
        const dir = translationDirection.value;

        if (!text) {
            showToast("يُرجى إدخال النص المطلوب ترجمته.", true);
            return;
        }

        translateSubmitBtn.disabled = true;
        translateSubmitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري الترجمة...';
        translateOutputText.textContent = 'جاري الترجمة القانونية...';

        try {
            const response = await fetch('/api/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: text, direction: dir })
            });

            if (!response.ok) throw new Error();
            const data = await response.json();

            translateOutputText.textContent = data.translated || '';
            
            // Adjust text direction based on output language
            if (dir === 'ar-to-en') {
                translateOutputText.style.direction = 'ltr';
                translateOutputText.style.textAlign = 'left';
            } else {
                translateOutputText.style.direction = 'rtl';
                translateOutputText.style.textAlign = 'right';
            }
            
            showToast("تمت الترجمة بنجاح.");
        } catch (error) {
            translateOutputText.textContent = 'فشلت الترجمة. يُرجى مراجعة الإعدادات ومفتاح API.';
            showToast("حدث خطأ أثناء الترجمة القانونية.", true);
        } finally {
            translateSubmitBtn.disabled = false;
            translateSubmitBtn.innerHTML = '<i class="fa-solid fa-language"></i> ترجمة النص';
        }
    });
}

// ============================================================
// Legislation Updates Logic
// ============================================================
function initUpdates() {
    const checkUpdatesBtn = document.getElementById('check-updates-btn');
    if (!checkUpdatesBtn) return;

    checkUpdatesBtn.addEventListener('click', async () => {
        checkUpdatesBtn.disabled = true;
        checkUpdatesBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري فحص الوقائع المصرية...';
        
        try {
            const response = await fetch('/api/updates/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (!response.ok) throw new Error();
            const updates = await response.json();
            
            renderUpdates(updates);
            showToast("تم فحص وتحديث التشريعات بنجاح.");
        } catch (error) {
            showToast("فشل التحقق من تحديثات جديدة.", true);
        } finally {
            checkUpdatesBtn.disabled = false;
            checkUpdatesBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> فحص التحديثات الجديدة (AI)';
        }
    });
}

async function loadUpdates() {
    const container = document.getElementById('updates-list-container');
    if (!container) return;
    
    container.innerHTML = '<div class="loading-spinner">جاري تحميل التحديثات التشريعية...</div>';
    
    try {
        const response = await fetch('/api/updates');
        if (!response.ok) throw new Error();
        const updates = await response.json();
        
        renderUpdates(updates);
    } catch (error) {
        container.innerHTML = '<div style="color:#EF4444; padding:20px; text-align:center;">حدث خطأ أثناء تحميل التحديثات.</div>';
    }
}

function renderUpdates(updates) {
    const container = document.getElementById('updates-list-container');
    if (!container) return;

    if (updates.length === 0) {
        container.innerHTML = '<div style="color:var(--text-muted); padding:30px; text-align:center;">لا توجد أي تحديثات تشريعية مسجلة حالياً. اضغط زر الفحص في الأعلى.</div>';
        return;
    }

    container.innerHTML = updates.map(u => `
        <div class="law-card update-card" style="border-right: 4px solid var(--accent-blue);">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 12px;">
                <h3 style="margin: 0; font-size: 1.1rem; color: var(--accent-blue);"><i class="fa-solid fa-circle-exclamation"></i> ${u.law_name}</h3>
                <span class="badge" style="background: rgba(14, 165, 233, 0.1); color: var(--accent-blue);">${u.date}</span>
            </div>
            <div style="margin-bottom: 10px;">
                <span class="badge" style="background: rgba(249, 115, 22, 0.1); color: #f97316; border-color: #f97316; font-size: 11px;">${u.type}</span>
            </div>
            <p style="font-size: 0.95rem; line-height: 1.6; margin: 0 0 12px 0;"><strong>التفاصيل:</strong> ${u.description}</p>
            ${u.impact ? `
                <div style="background: rgba(14, 165, 233, 0.05); padding: 10px; border-radius: 4px; font-size: 13px;">
                    <strong>الأثر القانوني والعملي:</strong> ${u.impact}
                </div>
            ` : ''}
        </div>
    `).join('');
}

// ============================================================
// Initialize all features on DOMContentLoaded
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initContractBuilder();
    initAnalyzer();
    initCaseManager();
    initCalculator();
    initCompare();
    initTranslate();
    initUpdates();
});

function setupMobileNavigation() {
    const menuToggle = document.getElementById('mobile-menu-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebar.classList.toggle('open');
            const icon = menuToggle.querySelector('i');
            if (sidebar.classList.contains('open')) {
                icon.className = 'fa-solid fa-xmark';
            } else {
                icon.className = 'fa-solid fa-bars';
            }
        });
        
        // Close sidebar if user clicks outside of it on mobile
        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !menuToggle.contains(e.target)) {
                sidebar.classList.remove('open');
                const icon = menuToggle.querySelector('i');
                if (icon) icon.className = 'fa-solid fa-bars';
            }
        });
    }
}
