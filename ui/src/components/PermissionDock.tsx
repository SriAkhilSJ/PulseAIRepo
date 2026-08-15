import type { Component } from "solid-js";
import { Icon } from "./Icon";

interface PermissionDockProps {
  onApprove: () => void;
  onDeny: () => void;
}

export const PermissionDock: Component<PermissionDockProps> = (props) => (
  <section class="permission-dock" aria-label="Permission required">
    <div class="permission-head">
      <Icon name="lock" size={15} />
      <div><strong>Permission required</strong><span>Pulse wants to edit a tracked file.</span></div>
    </div>
    <button class="permission-file" type="button">
      <Icon name="file" size={14} />
      <span>src/auth/session.ts</span>
      <span class="diff-add">+12</span>
      <span class="diff-del">−4</span>
      <Icon name="chevron" size={12} />
    </button>
    <div class="permission-actions">
      <button class="text-action" type="button" onClick={props.onDeny}>Deny</button>
      <span class="permission-action-spacer" />
      <button class="text-action" type="button">Open native diff</button>
      <button class="approve-button" type="button" onClick={props.onApprove}>Approve</button>
    </div>
  </section>
);
