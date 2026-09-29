// URLs por defecto: los tres microservicios publicados por Nginx en la VM
// (127.0.0.1 en la VM, expuestos por Nginx bajo /auth y /soap -- no se
// exponen los puertos crudos 5000/5001 directo a Internet, ver
// deploy/nginx-auth-proxy.conf y deploy/nginx-soap-proxy.conf).
const DEFAULT_AUTH_URL = "http://34.51.89.7/auth";
const DEFAULT_BOOKS_URL = "http://34.51.89.7/soap";
const DEFAULT_IMAGE_BASE_URL = "http://34.51.89.7/library";
const PAGE_SIZE = 9;
const STATUS_POLL_MS = 10000;

const K = { auth: "catalog.auth-url", books: "catalog.books-url", image: "catalog.image-base-url" };

let books = [];
let currentPage = 1;
let editingIsbn = null; // null = modal en modo "agregar"; string = modo "editar"
let statusTimer = null;

const el = (id) => document.getElementById(id);
const elements = {
  loginScreen: el("login-screen"), appScreen: el("app-screen"),
  loginForm: el("login-form"), registerForm: el("register-form"),
  loginEmail: el("login-email"), loginPassword: el("login-password"), loginError: el("login-error"),
  registerError: el("register-error"), registerOk: el("register-ok"),
  authUrl: el("auth-url"), booksUrl: el("books-url"), imageBaseUrl: el("image-base-url"),
  sessionUser: el("session-user"),
  tabCatalog: el("tab-catalog"), tabStatus: el("tab-status"),
  catalogView: el("catalog-view"), statusView: el("status-view"),
  grid: el("book-grid"), pagination: el("pagination"), summary: el("summary"), status: el("status"),
  template: el("book-template"),
  modal: el("book-modal"), modalTitle: el("book-modal-title"), modalForm: el("book-form"), modalError: el("book-form-error")
};

function urls() {
  return {
    auth: (elements.authUrl.value || DEFAULT_AUTH_URL).trim().replace(/\/+$/, ""),
    books: (elements.booksUrl.value || DEFAULT_BOOKS_URL).trim().replace(/\/+$/, ""),
    image: (elements.imageBaseUrl.value || DEFAULT_IMAGE_BASE_URL).trim().replace(/\/+$/, "")
  };
}

elements.authUrl.value = localStorage.getItem(K.auth) || DEFAULT_AUTH_URL;
elements.booksUrl.value = localStorage.getItem(K.books) || DEFAULT_BOOKS_URL;
elements.imageBaseUrl.value = localStorage.getItem(K.image) || DEFAULT_IMAGE_BASE_URL;

el("save-urls").addEventListener("click", () => {
  localStorage.setItem(K.auth, elements.authUrl.value.trim());
  localStorage.setItem(K.books, elements.booksUrl.value.trim());
  localStorage.setItem(K.image, elements.imageBaseUrl.value.trim());
});

// ------------------------------------------------------------- utilidades
function resolveImageUrl(value) {
  if (!value) return "";
  const base = urls().image;
  if (!base) return "";
  // value viene como ruta absoluta (/uploads/...) del XML de /books/images;
  // new URL(value, base) la resolvería contra el ORIGEN de base (perdiendo
  // el prefijo /library), por eso se concatena como texto en vez de
  // resolverla como URL relativa.
  try {
    return new URL(base + value).toString();
  } catch {
    return "";
  }
}

function textOf(node, ...names) {
  for (const name of names) {
    const value = node.querySelector(name)?.textContent?.trim();
    if (value) return value;
  }
  return "No disponible";
}

function parseBooks(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("El XML recibido no es válido.");
  const nodes = [...doc.querySelectorAll("books > book, book")];
  const uniqueNodes = [...new Set(nodes)];
  if (!uniqueNodes.length) return [];
  return uniqueNodes.map((node) => ({
    title: textOf(node, "title", "bookTitle"), isbn: textOf(node, "isbn"),
    genre: textOf(node, "genre", "category", "categoria"),
    price: textOf(node, "price", "precio"), authors: textOf(node, "authors", "author", "autores"),
    stock: textOf(node, "stock", "quantity", "existence"), year: textOf(node, "publicationYear", "year", "publishedYear"),
    image: node.querySelector("images > image > url, image > url, imageUrl, coverUrl")?.textContent?.trim() || ""
  }));
}

function parseCoverByIsbn(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("El XML de imágenes no es válido.");
  const map = new Map();
  for (const node of doc.querySelectorAll("books > book")) {
    const isbn = textOf(node, "isbn");
    const imageNodes = [...node.querySelectorAll("images > image")];
    const cover = imageNodes.find((img) => textOf(img, "isCover") === "true") || imageNodes[0];
    const url = cover?.querySelector("url")?.textContent?.trim();
    if (url) map.set(isbn, url);
  }
  return map;
}

// ---------------------------------------------------------------- login
function showLogin() {
  elements.loginScreen.hidden = false;
  elements.appScreen.hidden = true;
  stopStatusPolling();
}

async function showApp(email) {
  elements.loginScreen.hidden = true;
  elements.appScreen.hidden = false;
  elements.sessionUser.textContent = email || "";
  switchTab("catalog");
  await loadCatalog();
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.loginError.textContent = "";
  const email = elements.loginEmail.value.trim();
  const password = elements.loginPassword.value;
  const { ok, status, data } = await window.catalogApi.request(
    "POST", `${urls().auth}/login?format=json`, { email, password }
  );
  if (!ok) {
    elements.loginError.textContent = data?.error?.message || `No se pudo iniciar sesión (HTTP ${status}).`;
    return;
  }
  elements.loginPassword.value = "";
  await showApp(data.user?.email || email);
});

el("show-register").addEventListener("click", () => {
  elements.loginForm.hidden = true; elements.registerForm.hidden = false;
});
el("show-login").addEventListener("click", () => {
  elements.registerForm.hidden = true; elements.loginForm.hidden = false;
});

elements.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.registerError.textContent = ""; elements.registerOk.textContent = "";
  const payload = {
    nombre: el("reg-nombre").value.trim(),
    apellido_paterno: el("reg-apellido-paterno").value.trim(),
    apellido_materno: el("reg-apellido-materno").value.trim(),
    email: el("reg-email").value.trim(),
    password: el("reg-password").value
  };
  const { ok, status, data } = await window.catalogApi.request(
    "POST", `${urls().auth}/register?format=json`, payload
  );
  if (!ok) {
    const detalle = data?.error?.details?.map((d) => d.message).join(" ");
    elements.registerError.textContent = detalle || data?.error?.message || `No se pudo registrar (HTTP ${status}).`;
    return;
  }
  elements.registerOk.textContent = data.message || "Cuenta creada. Ya puedes iniciar sesión.";
  elements.registerForm.reset();
});

el("logout-button").addEventListener("click", async () => {
  await window.catalogApi.request("POST", `${urls().auth}/logout?format=json`);
  await window.catalogApi.clearSession();
  showLogin();
});

// --------------------------------------------------------------- tabs
function switchTab(tab) {
  const isCatalog = tab === "catalog";
  elements.tabCatalog.classList.toggle("active", isCatalog);
  elements.tabStatus.classList.toggle("active", !isCatalog);
  elements.catalogView.hidden = !isCatalog;
  elements.statusView.hidden = isCatalog;
  if (isCatalog) stopStatusPolling(); else startStatusPolling();
}
elements.tabCatalog.addEventListener("click", () => switchTab("catalog"));
elements.tabStatus.addEventListener("click", () => switchTab("status"));

// ------------------------------------------------------- semáforo (vista 2)
function setDot(prefix, up, statusCode) {
  const dot = el(`${prefix}-dot`);
  dot.className = `dot ${up ? "dot-up" : "dot-down"}`;
  el(`${prefix}-status-text`).textContent = up ? "UP" : `DOWN${statusCode ? ` (HTTP ${statusCode})` : ""}`;
}

async function checkStatus() {
  const { auth, books: booksUrl } = urls();
  el("auth-status-url").textContent = `${auth}/health`;
  el("books-status-url").textContent = `${booksUrl}/health`;
  const [authResult, booksResult] = await Promise.all([
    window.catalogApi.ping(`${auth}/health`),
    window.catalogApi.ping(`${booksUrl}/health`)
  ]);
  setDot("auth", authResult.up, authResult.status);
  setDot("books", booksResult.up, booksResult.status);
}

function startStatusPolling() {
  checkStatus();
  stopStatusPolling();
  statusTimer = setInterval(checkStatus, STATUS_POLL_MS);
}
function stopStatusPolling() {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
}

// ------------------------------------------------------- catálogo (vista 1)
function render() {
  const totalPages = Math.max(1, Math.ceil(books.length / PAGE_SIZE));
  currentPage = Math.min(currentPage, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const visibleBooks = books.slice(start, start + PAGE_SIZE);
  elements.grid.replaceChildren(...visibleBooks.map(renderCard));
  elements.summary.textContent = `${books.length} libro${books.length === 1 ? "" : "s"} · página ${currentPage} de ${totalPages}`;
  renderPagination(totalPages);
}

function renderCard(book) {
  const fragment = elements.template.content.cloneNode(true);
  const image = fragment.querySelector("img");
  const fallback = fragment.querySelector(".fallback-cover");
  fragment.querySelector("h3").textContent = book.title;
  fragment.querySelector(".genre").textContent = book.genre;
  for (const field of ["authors", "isbn", "stock", "year", "price"]) {
    fragment.querySelector(`[data-field="${field}"]`).textContent = book[field];
  }
  if (book.image) {
    image.hidden = true; fallback.hidden = false;
    image.alt = `Portada de ${book.title}`;
    window.catalogApi.loadImage(book.image)
      .then((dataUrl) => { image.src = dataUrl; image.hidden = false; fallback.hidden = true; })
      .catch(() => { image.hidden = true; fallback.hidden = false; });
  } else { image.hidden = true; fallback.hidden = false; }

  fragment.querySelector(".edit-button").addEventListener("click", () => openBookModal(book));
  fragment.querySelector(".delete-button").addEventListener("click", () => deleteBook(book));
  return fragment;
}

function renderPagination(totalPages) {
  elements.pagination.replaceChildren();
  if (totalPages < 2) return;
  const addButton = (label, page, disabled = false, current = false) => {
    const button = document.createElement("button"); button.type = "button"; button.textContent = label;
    button.disabled = disabled; button.classList.toggle("active", current);
    button.setAttribute("aria-current", current ? "page" : "false");
    button.addEventListener("click", () => { currentPage = page; render(); }); elements.pagination.append(button);
  };
  addButton("‹", currentPage - 1, currentPage === 1);
  for (let page = 1; page <= totalPages; page++) addButton(String(page), page, false, page === currentPage);
  addButton("›", currentPage + 1, currentPage === totalPages);
}

async function loadCatalog() {
  const { books: booksUrl } = urls();
  elements.status.textContent = "Cargando catálogo XML…";
  try {
    books = parseBooks(await window.catalogApi.loadXml(`${booksUrl}/books`));
    try {
      const coverByIsbn = parseCoverByIsbn(await window.catalogApi.loadXml(`${booksUrl}/books/images`));
      for (const book of books) {
        const relativeUrl = coverByIsbn.get(book.isbn);
        if (relativeUrl && !book.image) book.image = resolveImageUrl(relativeUrl);
      }
    } catch {
      // Sin portadas (endpoint de imágenes no disponible): el catálogo se
      // muestra igual, con el placeholder "Libro" por libro.
    }
    currentPage = 1; elements.status.textContent = ""; render();
  } catch (error) {
    books = []; elements.grid.replaceChildren(); elements.pagination.replaceChildren();
    elements.summary.textContent = "No fue posible cargar el catálogo.";
    elements.status.textContent = error.message;
  }
}

el("reload-button").addEventListener("click", loadCatalog);

// ------------------------------------------------------- CRUD (modal)
function openBookModal(book) {
  editingIsbn = book ? book.isbn : null;
  elements.modalError.textContent = "";
  elements.modalTitle.textContent = book ? `Editar «${book.title}»` : "Agregar libro";
  el("book-isbn").value = book ? book.isbn : "";
  el("book-isbn").disabled = Boolean(book); // el isbn no se edita, es la llave de la fila
  el("book-title").value = book ? book.title : "";
  el("book-year").value = book && book.year !== "No disponible" ? book.year : "";
  el("book-price").value = book && book.price !== "No disponible" ? String(book.price).replace(/[^0-9.]/g, "") : "";
  el("book-stock").value = book && book.stock !== "No disponible" ? book.stock : "";
  el("book-category").value = book && book.genre !== "No disponible" ? book.genre : "";
  el("book-format").value = "";
  el("book-authors").value = book && book.authors !== "No disponible" ? book.authors : "";
  elements.modal.hidden = false;
  el("book-title").focus();
}

function closeBookModal() {
  elements.modal.hidden = true;
  editingIsbn = null;
}

el("add-button").addEventListener("click", () => openBookModal(null));
el("book-cancel").addEventListener("click", closeBookModal);
elements.modal.addEventListener("click", (event) => { if (event.target === elements.modal) closeBookModal(); });

elements.modalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.modalError.textContent = "";
  const payload = {
    isbn: el("book-isbn").value.trim(),
    title: el("book-title").value.trim(),
    publicationYear: Number(el("book-year").value),
    price: Number(el("book-price").value),
    stock: Number(el("book-stock").value),
    category: el("book-category").value.trim(),
    format: el("book-format").value.trim(),
    authors: el("book-authors").value.trim()
  };
  const { books: booksUrl } = urls();
  const isEdit = Boolean(editingIsbn);
  const method = isEdit ? "PUT" : "POST";
  const target = isEdit ? `${booksUrl}/books/${encodeURIComponent(editingIsbn)}?format=json` : `${booksUrl}/books?format=json`;
  const { ok, status, data } = await window.catalogApi.request(method, target, payload);
  if (!ok) {
    elements.modalError.textContent = data?.error || `No se pudo guardar (HTTP ${status}).`;
    return;
  }
  closeBookModal();
  await loadCatalog();
});

async function deleteBook(book) {
  if (!confirm(`¿Eliminar «${book.title}» (ISBN ${book.isbn})? Esta acción no se puede deshacer.`)) return;
  const { books: booksUrl } = urls();
  const { ok, status, data } = await window.catalogApi.request(
    "DELETE", `${booksUrl}/books/${encodeURIComponent(book.isbn)}?format=json`
  );
  if (!ok) {
    alert(data?.error || `No se pudo eliminar (HTTP ${status}).`);
    return;
  }
  await loadCatalog();
}

// -------------------------------------------------------------- arranque
showLogin();
