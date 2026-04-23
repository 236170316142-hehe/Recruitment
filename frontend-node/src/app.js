const path = require("path");
const express = require("express");
const morgan = require("morgan");
const dotenv = require("dotenv");

const { dashboardRouter } = require("./routes/dashboard");

dotenv.config();

const app = express();
const port = process.env.PORT || process.env.FRONTEND_PORT || 3000;

app.set("view engine", "ejs");
app.set("views", path.join(__dirname, "..", "views"));

app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use(morgan("dev"));
app.use("/static", express.static(path.join(__dirname, "..", "public")));

app.use("/", dashboardRouter);

app.listen(port, () => {
  console.log(`Dashboard running on http://localhost:${port}`);
});
