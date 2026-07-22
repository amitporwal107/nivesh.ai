package ai.nivesh.app.ui.dashboard;

import ai.nivesh.app.data.repo.HomeRepository;
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
public final class DashboardViewModel_Factory implements Factory<DashboardViewModel> {
  private final Provider<HomeRepository> repoProvider;

  public DashboardViewModel_Factory(Provider<HomeRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public DashboardViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static DashboardViewModel_Factory create(Provider<HomeRepository> repoProvider) {
    return new DashboardViewModel_Factory(repoProvider);
  }

  public static DashboardViewModel newInstance(HomeRepository repo) {
    return new DashboardViewModel(repo);
  }
}
