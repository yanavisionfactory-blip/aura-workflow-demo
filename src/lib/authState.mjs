import { createContext, useContext } from "react";

// The shared application shell is also used by offline showcases.
// Keep reading identity separate from API bootstrapping.
export const AuthContext = createContext(null);
export const useOptionalAuth = () => useContext(AuthContext);
