import { projectSchema, type Project } from "../domain/project";

let database: Promise<IDBDatabase> | undefined;
function open(): Promise<IDBDatabase> {
  database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open("junk-studio", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("blobs");
      request.result.createObjectStore("projects");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () =>
      reject(new Error("Close other JUNK tabs to update local storage."));
  });
  return database;
}
async function write(
  store: string,
  key: string,
  value: unknown
): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(store, "readwrite");
    transaction.objectStore(store).put(value, key);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("Local save was interrupted."));
  });
}
async function read(store: string, key: string): Promise<unknown> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db.transaction(store).objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function saveBlob(id: string, blob: Blob): Promise<void> {
  await write("blobs", id, blob);
}
export async function loadBlob(id: string): Promise<Blob | undefined> {
  const blob = await read("blobs", id);
  if (blob === undefined || blob instanceof Blob) return blob;
  throw new Error(
    "Saved media has an invalid format. Import the project bundle again."
  );
}
export async function saveProject(project: Project): Promise<void> {
  await write("projects", "current", projectSchema.parse(project));
}
export async function loadProject(): Promise<Project | undefined> {
  const value = await read("projects", "current");
  return value === undefined ? undefined : projectSchema.parse(value);
}
