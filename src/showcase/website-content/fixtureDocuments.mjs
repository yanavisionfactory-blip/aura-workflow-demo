// Deliberately separate from the signed-in app's session attachment store.
export const getAttachedDocuments = () => [];
export const subscribeDocuments = (listener) => { listener([]); return () => {}; };
export const attachDocument = () => {};
export const removeDocument = () => {};
