import React from "react";

import {
  AWSProviderBadge,
  AzureProviderBadge,
  GCPProviderBadge,
  GitHubProviderBadge,
  KS8ProviderBadge,
  M365ProviderBadge,
} from "../icons/providers-badge";

export const CustomProviderInputAWS = () => {
  return (
    <div className="flex items-center gap-x-2">
      <AWSProviderBadge width={25} height={25} />
      <p className="text-sm">Amazon Web Services</p>
    </div>
  );
};

export const CustomProviderInputAzure = () => {
  return (
    <div className="flex items-center gap-x-2">
      <AzureProviderBadge width={25} height={25} />
      <p className="text-sm">Azure</p>
    </div>
  );
};

export const CustomProviderInputM365 = () => {
  return (
    <div className="flex items-center gap-x-2">
      <M365ProviderBadge width={25} height={25} />
      <p className="text-sm">Microsoft 365</p>
    </div>
  );
};

export const CustomProviderInputGCP = () => {
  return (
    <div className="flex items-center gap-x-2">
      <GCPProviderBadge width={25} height={25} />
      <p className="text-sm">Google Cloud Platform</p>
    </div>
  );
};

export const CustomProviderInputKubernetes = () => {
  return (
    <div className="flex items-center gap-x-2">
      <KS8ProviderBadge width={25} height={25} />
      <p className="text-sm">Kubernetes</p>
    </div>
  );
};

export const CustomProviderInputGitHub = () => {
  return (
    <div className="flex items-center gap-x-2">
      <GitHubProviderBadge width={25} height={25} />
      <p className="text-sm">GitHub</p>
    </div>
  );
};
