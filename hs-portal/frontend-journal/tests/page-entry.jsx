import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../src/auth.jsx";
import CoverLetterEdit from "../src/pages/CoverLetterEdit.jsx";

createRoot(document.getElementById("root")).render(
  <AuthProvider>
    <MemoryRouter initialEntries={["/cover-letters/new"]}>
      <Routes>
        <Route path="/cover-letters/:id" element={<CoverLetterEdit />} />
      </Routes>
    </MemoryRouter>
  </AuthProvider>
);
