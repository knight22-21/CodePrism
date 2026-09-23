import { EventEmitter } from "events";

/** Represents a user in the system. */
interface User {
  id: number;
  name: string;
  email: string;
}

type UserId = number;

/** Manages user records. */
class UserService extends EventEmitter {
  private users: Map<UserId, User> = new Map();

  /** Add a new user and emit 'added'. */
  addUser(user: User): void {
    this.users.set(user.id, user);
    this.emit("added", user);
  }

  getUser(id: UserId): User | undefined {
    return this.users.get(id);
  }

  listUsers(): User[] {
    return Array.from(this.users.values());
  }
}

const DEFAULT_TIMEOUT = 5000;

async function fetchUser(id: UserId): Promise<User | null> {
  const svc = new UserService();
  return svc.getUser(id) ?? null;
}

export { UserService, fetchUser, DEFAULT_TIMEOUT };
export type { User, UserId };
