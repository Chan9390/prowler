"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import * as z from "zod";

import { addProvider } from "@/actions/providers/providers";
import { ProviderTitleDocs } from "@/components/providers/workflow/provider-title-docs";
import { useToast } from "@/components/ui";
import { CustomButton, CustomInput } from "@/components/ui/custom";
import { Form } from "@/components/ui/form";
import { addProviderFormSchema, ApiError, ProviderType } from "@/types";

import { RadioGroupProvider } from "../../radio-group-provider";

export type FormValues = z.infer<typeof addProviderFormSchema>;

// Helper function for labels and placeholders
const getProviderFieldDetails = (providerType?: ProviderType) => {
  switch (providerType) {
    case "aws":
      return {
        label: "Account ID",
        placeholder: "e.g. 123456789012",
      };
    case "gcp":
      return {
        label: "Project ID",
        placeholder: "e.g. my-gcp-project",
      };
    case "azure":
      return {
        label: "Subscription ID",
        placeholder: "e.g. fc94207a-d396-4a14-a7fd-12ab34cd56ef",
      };
    case "kubernetes":
      return {
        label: "Kubernetes Context",
        placeholder: "e.g. my-cluster-context",
      };
    case "m365":
      return {
        label: "Domain ID",
        placeholder: "e.g. your-domain.onmicrosoft.com",
      };
    case "github":
      return {
        label: "Username",
        placeholder: "e.g. your-github-username",
      };
    default:
      return {
        label: "Provider UID",
        placeholder: "Enter the provider UID",
      };
  }
};

export const ConnectAccountForm = () => {
  const { toast } = useToast();
  const [prevStep, setPrevStep] = useState(1);
  const router = useRouter();

  const formSchema = addProviderFormSchema;

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      providerType: undefined,
      providerUid: "",
      providerAlias: "",
    },
  });

  const providerType = form.watch("providerType");
  const providerFieldDetails = getProviderFieldDetails(providerType);

  const isLoading = form.formState.isSubmitting;

  const onSubmitClient = async (values: FormValues) => {
    const formValues = { ...values };

    const formData = new FormData();
    Object.entries(formValues).forEach(
      ([key, value]) => value !== undefined && formData.append(key, value),
    );

    try {
      const data = await addProvider(formData);

      if (data?.errors && data.errors.length > 0) {
        // Handle server-side validation errors
        data.errors.forEach((error: ApiError) => {
          const errorMessage = error.detail;
          const pointer = error.source?.pointer;

          switch (pointer) {
            case "/data/attributes/provider":
              form.setError("providerType", {
                type: "server",
                message: errorMessage,
              });
              break;
            case "/data/attributes/uid":
            case "/data/attributes/__all__":
              form.setError("providerUid", {
                type: "server",
                message: errorMessage,
              });
              break;
            case "/data/attributes/alias":
              form.setError("providerAlias", {
                type: "server",
                message: errorMessage,
              });
              break;
            default:
              toast({
                variant: "destructive",
                title: "Oops! Something went wrong",
                description: errorMessage,
              });
          }
        });
        return;
      } else {
        // Go to the next step after successful submission
        const {
          id,
          attributes: { provider: providerType },
        } = data.data;

        router.push(`/providers/add-credentials?type=${providerType}&id=${id}`);
      }
    } catch (error: any) {
      // eslint-disable-next-line no-console
      console.error("Error during submission:", error);
      toast({
        variant: "destructive",
        title: "Submission Error",
        description: error.message || "Something went wrong. Please try again.",
      });
    }
  };

  const handleBackStep = () => {
    setPrevStep((prev) => prev - 1);
    //Deselect the providerType if the user is going back to the first step
    if (prevStep === 2) {
      form.setValue("providerType", undefined as unknown as ProviderType);
    }
    // Reset the providerUid and providerAlias fields when going back
    form.setValue("providerUid", "");
    form.setValue("providerAlias", "");
  };

  useEffect(() => {
    if (providerType) {
      setPrevStep(2);
    }
  }, [providerType]);

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmitClient)}
        className="flex flex-col space-y-4"
      >
        {/* Step 1: Provider selection */}
        {prevStep === 1 && (
          <RadioGroupProvider
            control={form.control}
            isInvalid={!!form.formState.errors.providerType}
            errorMessage={form.formState.errors.providerType?.message}
          />
        )}
        {/* Step 2: UID, alias, and credentials (if AWS) */}
        {prevStep === 2 && (
          <>
            <ProviderTitleDocs providerType={providerType} />
            <CustomInput
              control={form.control}
              name="providerUid"
              type="text"
              label={providerFieldDetails.label}
              labelPlacement="inside"
              placeholder={providerFieldDetails.placeholder}
              variant="bordered"
              isRequired
              isInvalid={!!form.formState.errors.providerUid}
            />
            <CustomInput
              control={form.control}
              name="providerAlias"
              type="text"
              label="Provider alias (optional)"
              labelPlacement="inside"
              placeholder="Enter the provider alias"
              variant="bordered"
              isRequired={false}
              isInvalid={!!form.formState.errors.providerAlias}
            />
          </>
        )}
        {/* Navigation buttons */}
        <div className="flex w-full justify-end sm:space-x-6">
          {/* Show "Back" button only in Step 2 */}
          {prevStep === 2 && (
            <CustomButton
              type="button"
              ariaLabel="Back"
              className="w-1/2 bg-transparent"
              variant="faded"
              size="lg"
              radius="lg"
              onPress={handleBackStep}
              startContent={!isLoading && <ChevronLeftIcon size={24} />}
              isDisabled={isLoading}
            >
              <span>Back</span>
            </CustomButton>
          )}
          {/* Show "Next" button in Step 2 */}
          {prevStep === 2 && (
            <CustomButton
              type="submit"
              ariaLabel="Next"
              className="w-1/2"
              variant="solid"
              color="action"
              size="lg"
              isLoading={isLoading}
              endContent={!isLoading && <ChevronRightIcon size={24} />}
            >
              {isLoading ? <>Loading</> : <span>Next</span>}
            </CustomButton>
          )}
        </div>
      </form>
    </Form>
  );
};
