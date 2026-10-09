
let isRegisterMode = false;

const userBadge = document.querySelector(".user-badge");
if (userBadge) {
  let lastActivityAt = Date.now();
  let refreshInProgress = false;

  for (const eventName of ["pointermove", "pointerdown", "keydown", "touchstart", "scroll"]) {
    document.addEventListener(eventName, () => {
      lastActivityAt = Date.now();
    }, { passive: true });
  }

  window.setInterval(async () => {
    const activityWasRecent = Date.now() - lastActivityAt < 5 * 60 * 1000;
    if (!activityWasRecent || refreshInProgress) return;

    refreshInProgress = true;
    try {
      const response = await fetch("/api/auth/refresh", { method: "POST" });
      if (response.status === 401) window.location.assign("/login");
    } catch (error) {
      console.error("No se pudo renovar la sesión", error);
    } finally {
      refreshInProgress = false;
    }
  }, 5 * 60 * 1000);
}

function toggleAuthMode() {
  isRegisterMode = !isRegisterMode;
  document.getElementById("title").innerText = isRegisterMode ? "Crear Cuenta" : "Iniciar Sesión";
  document.getElementById("btnSubmit").innerText = isRegisterMode ? "Registrar" : "Entrar";
  document.getElementById("toggleBtn").innerText = isRegisterMode 
    ? "¿Ya tienes cuenta? Inicia sesión" 
    : "¿No tienes cuenta? Regístrate aquí";
  
  const msg = document.getElementById("msg");
  if (msg) msg.innerText = "";
}

async function handleAuthSubmit() {
  const userEl = document.getElementById("username");
  const passEl = document.getElementById("password");
  const msg = document.getElementById("msg");

  const username = userEl.value.trim();
  const password = passEl.value;

  if (!username || !password) {
    msg.style.color = "#dc2626";
    msg.innerText = "Debes ingresar usuario y contraseña.";
    return;
  }

  if (username.length < 3) {
    msg.style.color = "#dc2626";
    msg.innerText = "El usuario debe tener al menos 3 caracteres.";
    return;
  }

  if (password.length < 6) {
    msg.style.color = "#dc2626";
    msg.innerText = "La contraseña debe tener al menos 6 caracteres.";
    return;
  }

  const endpoint = isRegisterMode ? "/api/auth/register" : "/api/auth/login";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    const data = await res.json();

    if (!res.ok) {
      msg.style.color = "#dc2626";
      msg.innerText = data.detail || "Error en la solicitud.";
      return;
    }

    if (isRegisterMode) {
      msg.style.color = "#16a34a";
      msg.innerText = data.message;
      userEl.value = "";
      passEl.value = "";
      isRegisterMode = false;
      document.getElementById("title").innerText = "Iniciar Sesión";
      document.getElementById("btnSubmit").innerText = "Entrar";
      document.getElementById("toggleBtn").innerText = "¿No tienes cuenta? Regístrate aquí";
      return;
    }

    window.location.href = "/";
  } catch (err) {
    msg.style.color = "#dc2626";
    msg.innerText = "No se pudo conectar con el servidor. Inténtalo otra vez.";
  }
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  } catch (err) {
    console.error("Error al salir", err);
  }
}