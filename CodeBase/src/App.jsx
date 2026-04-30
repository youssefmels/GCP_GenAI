import { useState } from "react";
import PostList from "./components/PostList";
import PostDetail from "./components/PostDetail";
import PostForm from "./components/PostForm";

// Views: "list" | "detail" | "create" | "edit"
export default function App() {
  const [view, setView] = useState("list");
  const [selectedId, setSelectedId] = useState(null);
  const [refresh, setRefresh] = useState(0);

  const navigate = (v, id = null) => {
    setView(v);
    setSelectedId(id);
  };

  const onSaved = () => {
    setRefresh((r) => r + 1);
    navigate("list");
  };

  return (
    <div className="app">
      <header className="header">
        <span className="logo" onClick={() => navigate("list")}>inkwell</span>
        <button className="btn-primary" onClick={() => navigate("create")}>
          + New Post
        </button>
      </header>

      <main className="main">
        {view === "list" && (
          <PostList
            key={refresh}
            onSelect={(id) => navigate("detail", id)}
            onEdit={(id) => navigate("edit", id)}
          />
        )}
        {view === "detail" && (
          <PostDetail
            id={selectedId}
            onBack={() => navigate("list")}
            onEdit={(id) => navigate("edit", id)}
            onDeleted={() => { setRefresh((r) => r + 1); navigate("list"); }}
          />
        )}
        {(view === "create" || view === "edit") && (
          <PostForm
            id={view === "edit" ? selectedId : null}
            onSaved={onSaved}
            onCancel={() => navigate("list")}
          />
        )}
      </main>
    </div>
  );
}