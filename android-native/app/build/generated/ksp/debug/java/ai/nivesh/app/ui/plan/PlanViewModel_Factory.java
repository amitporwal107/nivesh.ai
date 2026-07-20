package ai.nivesh.app.ui.plan;

import ai.nivesh.app.data.repo.PlansRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class PlanViewModel_Factory implements Factory<PlanViewModel> {
  private final Provider<PlansRepository> plansRepositoryProvider;

  public PlanViewModel_Factory(Provider<PlansRepository> plansRepositoryProvider) {
    this.plansRepositoryProvider = plansRepositoryProvider;
  }

  @Override
  public PlanViewModel get() {
    return newInstance(plansRepositoryProvider.get());
  }

  public static PlanViewModel_Factory create(Provider<PlansRepository> plansRepositoryProvider) {
    return new PlanViewModel_Factory(plansRepositoryProvider);
  }

  public static PlanViewModel newInstance(PlansRepository plansRepository) {
    return new PlanViewModel(plansRepository);
  }
}
