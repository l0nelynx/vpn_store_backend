import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, DataList, DetailRow, Empty, ListCard } from "../components/ui";

type Row = {
  id: number;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  after: object | null;
  created_at: string;
};

export default function AuditPage() {
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    api<Row[]>("/store/api/v1/audit").then(setRows);
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="page-title">Audit log</h2>
        <p className="muted mt-1">Publish, retry and configuration changes by operator.</p>
      </div>
      {!rows.length ? (
        <Empty title="No audit events" detail="Administrative changes will be recorded here." />
      ) : (
        <DataList
          table={
            <Card className="overflow-x-auto p-0">
              <table>
                <thead>
                  <tr>
                    <th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{new Date(row.created_at).toLocaleString()}</td>
                      <td>{row.actor}</td>
                      <td><Badge>{row.action}</Badge></td>
                      <td>{row.entity_type} {row.entity_id && `#${row.entity_id}`}</td>
                      <td>
                        <code className="block max-w-xl truncate text-xs text-muted-foreground">
                          {row.after ? JSON.stringify(row.after) : "—"}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          }
          cards={rows.map((row) => (
            <ListCard
              key={row.id}
              title={row.action}
              subtitle={new Date(row.created_at).toLocaleString()}
              badges={<Badge>{row.entity_type}{row.entity_id ? ` #${row.entity_id}` : ""}</Badge>}
              details={
                <>
                  <DetailRow label="Actor">{row.actor}</DetailRow>
                  <DetailRow label="Change">
                    <code className="block break-all text-xs text-muted-foreground">
                      {row.after ? JSON.stringify(row.after) : "—"}
                    </code>
                  </DetailRow>
                </>
              }
            />
          ))}
        />
      )}
    </div>
  );
}
