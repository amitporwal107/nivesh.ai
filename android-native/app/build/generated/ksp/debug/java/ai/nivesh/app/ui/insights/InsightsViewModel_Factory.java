package ai.nivesh.app.ui.insights;

import ai.nivesh.app.data.repo.InsightsRepository;
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
public final class InsightsViewModel_Factory implements Factory<InsightsViewModel> {
  private final Provider<InsightsRepository> repositoryProvider;

  public InsightsViewModel_Factory(Provider<InsightsRepository> repositoryProvider) {
    this.repositoryProvider = repositoryProvider;
  }

  @Override
  public InsightsViewModel get() {
    return newInstance(repositoryProvider.get());
  }

  public static InsightsViewModel_Factory create(Provider<InsightsRepository> repositoryProvider) {
    return new InsightsViewModel_Factory(repositoryProvider);
  }

  public static InsightsViewModel newInstance(InsightsRepository repository) {
    return new InsightsViewModel(repository);
  }
}
