const axios = require("axios");

let baseUrl = process.env.BACKEND_API_BASE || "http://localhost:8000";
if (!baseUrl.startsWith("http")) {
  baseUrl = `http://${baseUrl}`;
}
// On Render, internal services often need port 10000
if (baseUrl.includes("onrender.com") === false && !baseUrl.includes("localhost") && !baseUrl.match(/:\d+$/)) {
  baseUrl = `${baseUrl}:10000`;
}

const apiClient = axios.create({
  baseURL: baseUrl,
  timeout: 120000
});

module.exports = { apiClient };
