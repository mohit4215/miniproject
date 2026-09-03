// GlassBuddy — Interactive Animated Glass Mascot Companion

const QUOTES = [
  "Hi there! I'm <strong>GlassBuddy</strong> ✨ Ready to crush your study goals today?",
  "Deep focus mode activated! You've got this! 🚀",
  "Stay in the zone — consistent habits build mastery 💡",
  "Every 25 minutes of focus is a step toward excellence 🎯",
  "No distractions allowed! GlassBuddy is keeping watch 🛡️",
  "Take a deep breath. Focus on one task at a time 🧘",
  "Knowledge compounds like interest. Keep going! 📈"
];

let quoteIndex = 0;

export function initGlassBuddy() {
  setupSpeechCycles();
  setupClickInteractivity();
  setupTimerReactionListeners();
}

function setupSpeechCycles() {
  const speechElements = document.querySelectorAll(".gb-speech-text");
  if (!speechElements.length) return;

  function setQuote(text) {
    speechElements.forEach(el => {
      el.style.opacity = "0";
      el.style.transform = "translateY(4px)";
      setTimeout(() => {
        el.innerHTML = text;
        el.style.opacity = "1";
        el.style.transform = "none";
      }, 250);
    });
  }

  setInterval(() => {
    quoteIndex = (quoteIndex + 1) % QUOTES.length;
    setQuote(QUOTES[quoteIndex]);
  }, 10000);
}

function setupClickInteractivity() {
  document.querySelectorAll(".glassbuddy-avatar-wrap, .glassbuddy-compact-avatar").forEach(wrap => {
    wrap.style.cursor = "pointer";
    wrap.addEventListener("click", () => {
      wrap.classList.add("gb-bounce");
      setTimeout(() => wrap.classList.remove("gb-bounce"), 700);
      
      const funRemarks = [
        "Yay! Clicked by my favorite study partner! ✨",
        "Ready to grind? Let's start the timer! ⏱️",
        "GlassBuddy high five! ✋ Let's do this!",
        "Focused and clear as crystal glass! 💎"
      ];
      const randomRemark = funRemarks[Math.floor(Math.random() * funRemarks.length)];
      
      document.querySelectorAll(".gb-speech-text").forEach(el => {
        el.innerHTML = randomRemark;
      });
    });
  });
}

function setupTimerReactionListeners() {
  window.addEventListener("blur", () => {
    document.querySelectorAll(".gb-speech-text").forEach(el => {
      el.innerHTML = "Hey! Don't leave the tab during your focus session! ⚠️";
    });
  });

  document.addEventListener("sp-points", () => {
    document.querySelectorAll(".gb-speech-text").forEach(el => {
      el.innerHTML = "Woohoo! Session complete and points earned! 🏆🎉";
    });
  });
}

export function updateGlassBuddyMood(mood, customMsg) {
  const textEl = document.querySelector(".gb-speech-text");
  if (textEl && customMsg) {
    textEl.innerHTML = customMsg;
  }
}
